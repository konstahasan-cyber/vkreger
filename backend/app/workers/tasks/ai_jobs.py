"""AI background jobs.  Each job updates a ``jobs`` row the UI polls."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.analyst_service import run_review
from app.content.generator import generate_post
from app.core.exceptions import AppError, CostLimitExceeded
from app.db.session import SessionLocal, session_scope
from app.models.enums import JobStatus, LogLevel
from app.models.system import Job
from app.openai.provider import AIError
from app.services import project_service, queue_service
from app.services.audit import syslog
from app.services.job_service import finish_job
from app.vk.errors import VKError
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_job(job_id: int, fn: Callable[[Session, Job], dict[str, Any]]) -> dict:
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}
        job.status = JobStatus.RUNNING.value
        db.commit()
        try:
            result = fn(db, job)
            finish_job(job, result=result)
            db.commit()
            return result
        except (AppError, AIError, VKError) as exc:
            db.rollback()
            job = db.get(Job, job_id)
            message = getattr(exc, "message", None) or str(exc)
            finish_job(job, error=message)
            syslog(db, LogLevel.ERROR, f"job:{job.type}", f"Job #{job.id} failed: {message}", project_id=job.project_id)
            db.commit()
            return {"error": message}
        except Exception as exc:  # noqa: BLE001 — record any unexpected failure for the UI
            logger.exception("Job %s crashed", job_id)
            db.rollback()
            job = db.get(Job, job_id)
            finish_job(job, error=f"internal error: {type(exc).__name__}")
            syslog(db, LogLevel.ERROR, f"job:{job.type}", f"Job #{job.id} crashed: {type(exc).__name__}: {exc}",
                   project_id=job.project_id)
            db.commit()
            return {"error": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.ai_jobs.project_setup")
def project_setup_task(job_id: int) -> dict:
    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        data = project_service.run_setup(db, project, force=job.params.get("force", False))
        return {"proposal_keys": list(data)}

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.content_plan")
def content_plan_task(job_id: int) -> dict:
    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        items = project_service.generate_content_plan(db, project, days=job.params.get("days", 7),
                                                      count=job.params.get("count"),
                                                      force=job.params.get("force", False))
        return {"items": [i.id for i in items]}

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.generate_posts")
def generate_posts_task(job_id: int) -> dict:
    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        params = job.params
        ids = []
        for _ in range(max(1, min(int(params.get("count", 1)), 20))):
            if params.get("topic") is None and project_service_needs_plan(db, project.id):
                project_service.generate_content_plan(db, project, days=7, force=params.get("force", False))
            post = generate_post(db, project, topic=params.get("topic"), rubric_code=params.get("rubric_code"),
                                 angle=params.get("angle"), extra_instructions=params.get("instructions"),
                                 force=params.get("force", False), with_image=params.get("with_image"))
            ids.append(post.id)
            db.commit()
        return {"posts": ids}

    return run_job(job_id, fn)


def project_service_needs_plan(db: Session, project_id: int) -> bool:
    from app.content.generator import next_plan_item

    return next_plan_item(db, project_id) is None


@celery_app.task(name="app.workers.tasks.ai_jobs.launch_community")
def launch_community_task(job_id: int) -> dict:
    """Wizard final step: settings → pinned post → content plan → first queue."""
    from app.services import community_service

    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        params = job.params
        community = project.community
        result: dict[str, Any] = {"community_id": community.id}
        result["settings"] = community_service.apply_settings(
            db, community, description=params.get("description"), status=params.get("status"),
            website=project.website or None)
        db.commit()
        if (project.brand or {}).get("avatar") or (project.brand or {}).get("cover"):
            from app.services.brand_service import upload_design

            result["design"] = upload_design(db, project)
            db.commit()
        pinned = params.get("pinned_post")
        if pinned and pinned.get("text"):
            post = community_service.create_pinned_post(db, project, title=pinned.get("title", ""), text=pinned["text"])
            result["pinned_post"] = {"id": post.id, "status": post.status, "vk_post_id": post.vk_post_id}
            db.commit()
        community_service.activate_project(db, project)
        db.commit()
        if params.get("first_queue", True):
            project_service.generate_content_plan(db, project, days=7, force=params.get("force", False))
            db.commit()
            result["queue"] = queue_service.fill_queue(db, project, automatic=False, force=params.get("force", False),
                                                       max_new=int(params.get("queue_size", 3)))
        return result

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.autopilot_fill_queues")
def autopilot_fill_queues() -> dict:
    results = {}
    with session_scope() as db:
        projects = queue_service.autopilot_projects(db)
        for project in projects:
            try:
                results[project.id] = queue_service.fill_queue(db, project, automatic=True)
                db.commit()
            except (AppError, VKError) as exc:
                db.rollback()
                syslog(db, LogLevel.ERROR, "autopilot", f"Project #{project.id}: {exc}", project_id=project.id)
                db.commit()
    return results


@celery_app.task(name="app.workers.tasks.ai_jobs.analyst_reviews")
def analyst_reviews() -> dict:
    results = {}
    with session_scope() as db:
        for project in queue_service.autopilot_projects(db):
            try:
                results[project.id] = {k: v for k, v in run_review(db, project).items() if k != "review"}
                db.commit()
            except CostLimitExceeded as exc:
                db.rollback()
                results[project.id] = {"skipped": exc.message}
            except (AppError, AIError) as exc:
                db.rollback()
                syslog(db, LogLevel.ERROR, "analyst", f"Project #{project.id}: {exc}", project_id=project.id)
                db.commit()
    return results


@celery_app.task(name="app.workers.tasks.ai_jobs.analyst_review_job")
def analyst_review_job(job_id: int) -> dict:
    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        return run_review(db, project, automatic=False, force_due=True)

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.fill_queue_job")
def fill_queue_job(job_id: int) -> dict:
    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        return queue_service.fill_queue(db, project, automatic=False, force=job.params.get("force", False),
                                        max_new=int(job.params.get("max_new", 5)))

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.brand_import")
def brand_import_task(job_id: int) -> dict:
    from app.content.brand_import import BrandImportError, fetch_site
    from app.services.brand_service import apply_brand_analysis

    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        signals = job.params.get("signals")
        if signals is None:
            try:
                signals = fetch_site(job.params["url"]).to_dict()
            except BrandImportError as exc:
                raise AppError(str(exc)) from exc
        style = apply_brand_analysis(db, project, signals, force=job.params.get("force", False))
        return {"palette": style.get("palette"), "visual_style": style.get("visual_style")}

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.design_generate")
def design_generate_task(job_id: int) -> dict:
    from app.services.brand_service import generate_design, upload_design

    def fn(db: Session, job: Job) -> dict:
        project = project_service.get_project(db, job.project_id)
        result = generate_design(db, project, job.params.get("kinds", ["avatar", "cover"]),
                                 force=job.params.get("force", False))
        db.commit()
        if job.params.get("upload") and project.community:
            result["upload"] = upload_design(db, project, list(result))
        return result

    return run_job(job_id, fn)
