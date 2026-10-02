from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.aggregator import aggregate_project
from app.api.deps import require
from app.core.rbac import Permission
from app.db.base import utcnow
from app.db.session import get_db
from app.models.analytics import PostStatSnapshot
from app.models.content import Post
from app.models.enums import PostStatus, ProjectStatus
from app.models.inbox import Lead
from app.models.project import Project
from app.models.user import User
from app.services.dashboard_service import dashboard

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    return dashboard(db)


@router.get("/analytics/overview")
def overview(days: int = 30, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    projects = db.execute(select(Project).where(Project.status != ProjectStatus.ARCHIVED.value)).scalars().all()
    result = []
    for project in projects:
        agg = aggregate_project(db, project.id, last_n=500, days=days)
        leads = db.execute(select(func.count()).select_from(Lead).where(Lead.project_id == project.id,
                                                                     Lead.created_at >= since)).scalar_one()
        result.append({"project_id": project.id, "name": project.name, "posts": agg["posts_count"],
                       "views": agg["total_views"], "avg_views": agg["avg_views"],
                       "avg_engagement_rate": agg["avg_engagement_rate"], "clicks": agg["total_clicks"], "leads": leads,
                       "best_category": agg["best_categories"][0]["category"] if agg["best_categories"] else None})
    return result


@router.get("/analytics/projects/{project_id}")
def project_analytics(project_id: int, last_n: int = 30, days: int | None = None, db: Session = Depends(get_db),
                      _: User = Depends(require(Permission.VIEW))) -> dict:
    return aggregate_project(db, project_id, last_n=min(last_n, 500), days=days)


@router.get("/analytics/posts/{post_id}/history")
def post_history(post_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    rows = db.execute(select(PostStatSnapshot).where(PostStatSnapshot.post_id == post_id)
                      .order_by(PostStatSnapshot.collected_at)).scalars()
    return [{"at": r.collected_at, "views": r.views, "likes": r.likes, "comments": r.comments, "reposts": r.reposts,
             "clicks": r.clicks, "reach": r.reach} for r in rows]


@router.get("/analytics/daily")
def daily(project_id: int | None = None, days: int = 30, db: Session = Depends(get_db),
          _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    since = utcnow() - timedelta(days=days)
    day = func.date(Post.published_at)
    query = select(day, func.count()).where(Post.status == PostStatus.PUBLISHED.value, Post.published_at >= since)
    if project_id:
        query = query.where(Post.project_id == project_id)
    return [{"date": str(d), "posts": n} for d, n in db.execute(query.group_by(day).order_by(day)).all()]


@router.post("/analytics/collect")
def collect(_: User = Depends(require(Permission.MANAGE_CONTENT))) -> dict:
    from app.workers.tasks.maintenance import collect_analytics

    return {"task_id": str(collect_analytics.delay().id)}
