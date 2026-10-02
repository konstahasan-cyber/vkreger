"""Autopilot: keep each project's publication queue filled for the next N days."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.generator import generate_post, next_plan_item
from app.content.slots import free_slots
from app.core.exceptions import CostLimitExceeded
from app.db.base import utcnow
from app.models.content import Post
from app.models.enums import LogLevel, PostStatus, ProjectStatus
from app.models.project import Project
from app.openai.provider import AIError
from app.openai.service import AIService
from app.services.audit import syslog
from app.services.project_service import generate_content_plan

QUEUED = [PostStatus.DRAFT.value, PostStatus.APPROVED.value, PostStatus.SCHEDULED.value]


def queued_count(db: Session, project_id: int, horizon_end) -> int:  # noqa: ANN001
    return db.execute(
        select(func.count()).select_from(Post).where(
            Post.project_id == project_id, Post.status.in_(QUEUED),
            (Post.scheduled_at.is_(None)) | (Post.scheduled_at <= horizon_end),
        )
    ).scalar_one()


def fill_queue(db: Session, project: Project, *, horizon_days: int | None = None, max_new: int = 10,
               automatic: bool = True, force: bool = False) -> dict:
    """Generate posts for free slots within the horizon.

    New posts are ``scheduled`` when the project has ``auto_approve``, otherwise they stay
    ``draft`` with a planned time and wait for operator approval.
    """
    ai = AIService(db)
    horizon_days = horizon_days or int(ai.rs.QUEUE_HORIZON_DAYS)
    result = {"created": [], "skipped": None}
    if project.community is None:
        result["skipped"] = "no community"
        return result
    slots = free_slots(db, project, max_new, horizon_days=horizon_days)
    # drafts already waiting for approval occupy slots too
    pending_drafts = db.execute(
        select(Post.scheduled_at).where(Post.project_id == project.id, Post.status == PostStatus.DRAFT.value,
                                        Post.scheduled_at.is_not(None))
    ).scalars().all()
    taken = {d.replace(second=0, microsecond=0) for d in pending_drafts if d}
    slots = [s for s in slots if s not in taken]
    if not slots:
        result["skipped"] = "queue is full"
        return result
    try:
        for slot in slots:
            if next_plan_item(db, project.id) is None:
                generate_content_plan(db, project, days=7, automatic=automatic, force=force, ai=ai)
            post = generate_post(db, project, automatic=automatic, force=force, ai=ai)
            post.scheduled_at = slot
            warn = post.generation_metadata.get("similarity_warning")
            post.status = PostStatus.SCHEDULED.value if project.auto_approve and not warn else PostStatus.DRAFT.value
            result["created"].append(post.id)
            db.commit()
    except CostLimitExceeded as exc:
        syslog(db, LogLevel.WARNING, "autopilot", f"Project #{project.id}: {exc.message}", project_id=project.id)
        result["skipped"] = "cost limit"
    except AIError as exc:
        syslog(db, LogLevel.ERROR, "autopilot", f"Project #{project.id}: AI error: {exc}", project_id=project.id)
        result["skipped"] = "ai error"
    db.flush()
    return result


def autopilot_projects(db: Session) -> list[Project]:
    return list(db.execute(
        select(Project).where(Project.autopilot.is_(True), Project.status == ProjectStatus.ACTIVE.value)
    ).scalars())


def posts_today(db: Session) -> int:
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.execute(
        select(func.count()).select_from(Post).where(Post.published_at >= start, Post.published_at < start + timedelta(days=1))
    ).scalar_one()
