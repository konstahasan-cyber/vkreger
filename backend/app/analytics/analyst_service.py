"""Periodic strategy review by the ANALYST agent (not after every post)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.content import ContentPlanItem, Post, Strategy
from app.models.enums import PlanItemStatus, PostStatus
from app.models.project import Project
from app.openai.agents import analyst
from app.openai.service import AIService
from app.services.project_service import active_strategy, save_strategy


def review_due(db: Session, project: Project, ai: AIService) -> tuple[bool, str]:
    last = db.execute(
        select(Strategy).where(Strategy.project_id == project.id, Strategy.source == "analyst")
        .order_by(Strategy.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    since = last.created_at if last else None
    if since and utcnow() - since < timedelta(days=int(ai.rs.ANALYST_MIN_INTERVAL_DAYS)):
        return False, "interval"
    query = select(func.count()).select_from(Post).where(
        Post.project_id == project.id, Post.status == PostStatus.PUBLISHED.value)
    if since:
        query = query.where(Post.published_at >= since)
    new_posts = db.execute(query).scalar_one()
    if new_posts < int(ai.rs.ANALYST_MIN_NEW_POSTS):
        return False, f"only {new_posts} new posts"
    return True, "ok"


def run_review(db: Session, project: Project, *, automatic: bool = True, force_due: bool = False) -> dict:
    ai = AIService(db)
    if not force_due:
        due, reason = review_due(db, project, ai)
        if not due:
            return {"skipped": reason}
    current = active_strategy(db, project.id)
    data = analyst.review(ai, db, project, current.data if current else None, automatic=automatic)
    result = {"review": data, "strategy_changed": False}
    if data.get("change_strategy"):
        new_data = dict(current.data if current else {})
        weights = {w["code"]: max(0.2, min(3.0, float(w["weight"]))) for w in data.get("rubric_weights", [])}
        for rubric in project.rubrics:
            if rubric.code in weights:
                rubric.weight = weights[rubric.code]
        times = [t for t in data.get("best_times", []) if isinstance(t, str) and len(t) == 5 and t[2] == ":"]
        if times:
            project.posting_times = times
            new_data["best_times"] = times
        new_data["analyst_recommendations"] = data.get("recommendations", [])
        save_strategy(db, project.id, new_data, source="analyst", reasoning=data.get("summary"))
        result["strategy_changed"] = True
    else:
        # record the review without changing the strategy so the interval logic still works
        if current:
            current.data = {**current.data, "last_review": {"at": utcnow().isoformat(), "summary": data.get("summary")}}
        save_strategy(db, project.id, current.data if current else {}, source="analyst", reasoning=data.get("summary"))
    codes = {r.code for r in project.rubrics if r.is_active}
    for idea in data.get("new_ideas", [])[:10]:
        if idea.get("topic"):
            db.add(ContentPlanItem(project_id=project.id, rubric_code=idea.get("rubric_code") if idea.get("rubric_code") in codes else next(iter(sorted(codes)), "educational"),
                                   topic=idea["topic"], angle="idea from ANALYST", status=PlanItemStatus.PLANNED.value))
    db.flush()
    return result
