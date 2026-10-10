"""AI background jobs.  Each job updates a ``jobs`` row the UI polls."""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC
from typing import Any

from sqlalchemy.orm import Session

from app.analytics.analyst_service import run_review
from app.content.generator import generate_post
from app.core.exceptions import AppError, CostLimitExceeded
from app.db.session import SessionLocal, session_scope
from app.models.content import Post
from app.models.enums import JobStatus, LogLevel
from app.models.system import Job
from app.openai.provider import AIError
from app.services import project_service, queue_service
from app.services.audit import syslog
from app.services.job_service import create_job, finish_job
from app.services.publishing_service import schedule_post
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
        total = max(1, min(int(params.get("count", 1)), 60))
        for _ in range(total):
            if params.get("topic") is None and project_service_needs_plan(db, project.id):
                project_service.generate_content_plan(db, project, days=7, force=params.get("force", False))
            post = generate_post(db, project, topic=params.get("topic"), rubric_code=params.get("rubric_code"),
                                 angle=params.get("angle"), extra_instructions=params.get("instructions"),
                                 force=params.get("force", False), with_image=params.get("with_image"))
            ids.append(post.id)
            job.result = {"done": len(ids), "total": total}
            db.commit()
        if params.get("cadence_days"):
            planned = plan_cadence(project, len(ids), int(params["cadence_days"]), params.get("post_time"),
                                   params.get("start_date"))
            for post_id, when in zip(ids, planned, strict=True):
                post = db.get(Post, post_id)
                post.scheduled_at = when
                if params.get("auto_schedule") and post.community_id:
                    schedule_post(db, post, when)
            db.commit()
        return {"posts": ids, "done": len(ids), "total": total}

    return run_job(job_id, fn)


def plan_cadence(project, count: int, every_days: int, post_time: str | None, start: str | None) -> list:  # noqa: ANN001
    """Publication times: every ``every_days`` days at ``post_time`` (project timezone).

    ``post_time`` may list several times («10:00,19:00») — then each of those days gets several posts.
    """
    from datetime import date, datetime, time, timedelta

    from app.content.slots import tz

    zone = tz(project)
    raw = post_time or (project.posting_times or ["10:00"])[0]
    times = sorted({time(int(t.split(":")[0]), int(t.split(":")[1])) for t in str(raw).split(",") if ":" in t})
    times = times or [time(10, 0)]
    day = date.fromisoformat(start) if start else datetime.now(zone).date()
    earliest = datetime.now(zone) + timedelta(minutes=5)
    result = []
    while len(result) < count:
        for at in times:
            when = datetime.combine(day, at, tzinfo=zone)
            if when > earliest and len(result) < count:
                result.append(when.astimezone(UTC))
        day += timedelta(days=every_days if result else 1)
    return result


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


def stagger_times(post_times: list[str], minutes: int) -> str:
    """Shift publication times so groups of one network don't all post in the same minute."""
    out = []
    for value in post_times or ["10:00"]:
        hh, mm = (int(x) for x in value.split(":"))
        total = (hh * 60 + mm + minutes) % (24 * 60)
        out.append(f"{total // 60:02d}:{total % 60:02d}")
    return ",".join(out)


def posts_in_period(days: int, every_days: int, times_per_day: int) -> int:
    return max(1, -(-days // max(1, every_days)) * max(1, times_per_day))


@celery_app.task(name="app.workers.tasks.ai_jobs.network_launch")
def network_launch_task(job_id: int) -> dict:
    """Network: one shared AI strategy → a content plan per group (aware of the others) → posts per group."""
    from app.services import community_service, network_service

    def fn(db: Session, job: Job) -> dict:
        params = job.params
        network = params["network"]
        projects = [project_service.get_project(db, pid) for pid in params["project_ids"]]
        projects = [p for p in projects if p.network == network]
        if not projects:
            raise AppError("В сети нет групп для запуска")
        force = params.get("force", False)
        template = network_service.template_project(db, network)
        if template is None:
            template = projects[0]
            project_service.run_setup(db, template, force=force)
            db.commit()
        for project in projects:
            if project.id != template.id and not (project.rubrics and project.context_summary):
                network_service.copy_strategy(db, template, project)
            if project.community:
                community_service.activate_project(db, project)
        db.commit()

        days = int(params.get("days", 14))
        every = int(params.get("cadence_days", 1))
        times = params.get("post_times") or ["10:00"]
        count = min(posts_in_period(days, every, len(times)), 60)
        order = {p.id: i for i, p in enumerate(network_service.network_projects(db, network))}
        # plans one after another: each group sees the topics already taken by the others
        for project in projects:
            project_service.generate_content_plan(db, project, days=days, count=count, force=force)
            db.commit()
        children = {}
        for project in projects:
            child = create_job(db, "generate_posts", project_id=project.id, user_id=job.created_by, params={
                "count": count, "cadence_days": every, "post_time": stagger_times(times, 4 * order.get(project.id, 0)),
                "start_date": params.get("start_date"), "with_image": params.get("with_image"),
                "auto_schedule": params.get("auto_schedule", False), "force": force, "network": network,
            })
            db.commit()
            children[str(project.id)] = child.id
        for child_id in children.values():
            generate_posts_task.delay(child_id)
        return {"children": children, "posts_per_group": count}

    return run_job(job_id, fn)


@celery_app.task(name="app.workers.tasks.ai_jobs.network_dedupe")
def network_dedupe_task(job_id: int) -> dict:
    """Rewrite unpublished posts that look like posts of other groups in the network."""
    from app.content.generator import rewrite_post
    from app.services import network_service

    def fn(db: Session, job: Job) -> dict:
        from app.services.settings_service import load_runtime_settings

        rs = load_runtime_settings(db)
        pairs = network_service.similar_pairs(db, job.params["network"],
                                              semantic_threshold=float(rs.SIMILARITY_THRESHOLD),
                                              title_threshold=float(rs.TITLE_SIMILARITY_THRESHOLD))
        targets = list(dict.fromkeys(p["rewrite"]["id"] for p in pairs if p["can_rewrite"]))
        rewritten, failed = [], []
        for post_id in targets[:int(job.params.get("max", 100))]:
            post = db.get(Post, post_id)
            if post is None:
                continue
            try:
                rewrite_post(db, post, force=job.params.get("force", False))
                db.commit()
                rewritten.append(post_id)
            except (AppError, AIError) as exc:
                db.rollback()
                failed.append({"post": post_id, "error": getattr(exc, "message", str(exc))})
                if isinstance(exc, CostLimitExceeded):
                    break
        return {"similar_pairs": len(pairs), "rewritten": rewritten, "failed": failed}

    return run_job(job_id, fn)
