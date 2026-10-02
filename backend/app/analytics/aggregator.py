"""Aggregated statistics for dashboards and for the ANALYST agent."""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.content import Post
from app.models.enums import PostStatus
from app.models.inbox import Lead
from app.models.project import Project


def engagement_rate(stats: dict) -> float:
    views = stats.get("views") or 0
    if not views:
        return 0.0
    interactions = (stats.get("likes") or 0) + (stats.get("comments") or 0) + (stats.get("reposts") or 0)
    return round(100.0 * interactions / views, 2)


def aggregate_project(db: Session, project_id: int, *, last_n: int = 30, days: int | None = None) -> dict:
    project = db.get(Project, project_id)
    zone = ZoneInfo(project.timezone) if project and project.timezone else ZoneInfo("UTC")
    query = select(Post).where(Post.project_id == project_id, Post.status == PostStatus.PUBLISHED.value)
    if days:
        query = query.where(Post.published_at >= datetime.now(UTC) - timedelta(days=days))
    posts = list(db.execute(query.order_by(Post.published_at.desc()).limit(last_n)).scalars())
    rows = []
    for post in posts:
        stats = post.analytics or {}
        rows.append({
            "id": post.id, "title": post.title or post.topic or "", "category": post.category or "-",
            "views": stats.get("views", 0), "likes": stats.get("likes", 0), "comments": stats.get("comments", 0),
            "reposts": stats.get("reposts", 0), "clicks": stats.get("clicks"), "er": engagement_rate(stats),
            "hour": post.published_at.astimezone(zone).hour if post.published_at else None,
        })
    by_cat: dict[str, list[dict]] = defaultdict(list)
    by_hour: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_cat[row["category"]].append(row)
        if row["hour"] is not None:
            by_hour[row["hour"]].append(row)

    def _avg(items: list[dict], key: str) -> float:
        return round(sum((i.get(key) or 0) for i in items) / len(items), 2) if items else 0.0

    categories = sorted(
        ({"category": c, "posts": len(items), "avg_views": _avg(items, "views"), "engagement_rate": _avg(items, "er")}
         for c, items in by_cat.items()),
        key=lambda x: x["engagement_rate"], reverse=True,
    )
    hours = sorted(
        ({"hour": h, "posts": len(items), "engagement_rate": _avg(items, "er"), "avg_views": _avg(items, "views")}
         for h, items in by_hour.items()),
        key=lambda x: x["engagement_rate"], reverse=True,
    )
    ranked = sorted(rows, key=lambda r: r["er"], reverse=True)
    since = posts[-1].published_at if posts else None
    leads = None
    if since:
        leads = db.execute(select(func.count()).select_from(Lead).where(
            Lead.project_id == project_id, Lead.created_at >= since)).scalar_one()
    return {
        "posts_count": len(rows),
        "avg_views": _avg(rows, "views"),
        "avg_likes": _avg(rows, "likes"),
        "avg_engagement_rate": _avg(rows, "er"),
        "total_views": sum(r["views"] for r in rows),
        "total_clicks": sum(r["clicks"] or 0 for r in rows),
        "by_category": categories,
        "best_categories": categories[:3],
        "worst_categories": categories[-3:][::-1] if len(categories) > 3 else [],
        "best_hours": hours,
        "top_posts": ranked[:5],
        "worst_posts": ranked[-5:][::-1] if len(ranked) > 5 else [],
        "leads_count": leads,
        "posts": rows,
    }
