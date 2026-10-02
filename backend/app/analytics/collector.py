"""Collect post metrics from VK: wall.getById (views/likes/comments/reposts) and
stats.getPostReach (reach, link clicks — available to community admins)."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.models.analytics import PostStatSnapshot
from app.models.community import Community
from app.models.content import Post
from app.models.enums import LogLevel, PostStatus
from app.services.audit import syslog
from app.vk.errors import VKAPIError, VKError
from app.vk.factory import client_for_community


def collect_for_community(db: Session, community: Community, posts: list[Post]) -> int:
    by_vk_id = {p.vk_post_id: p for p in posts if p.vk_post_id}
    if not by_vk_id:
        return 0
    updated = 0
    with client_for_community(community, prefer_community_token=False) as client:
        ids = list(by_vk_id)
        for chunk_start in range(0, len(ids), 100):
            chunk = ids[chunk_start:chunk_start + 100]
            items = client.wall_get_by_id(community.vk_group_id, chunk)
            reach: dict[int, dict] = {}
            try:
                for start in range(0, len(chunk), 30):  # stats.getPostReach accepts up to 30 ids
                    for i, row in enumerate(client.post_reach(community.vk_group_id, chunk[start:start + 30])):
                        pid = int(row.get("post_id") or chunk[start + i])
                        reach[pid] = row
            except VKAPIError:
                pass  # not an admin / stats disabled — basic metrics are still collected
            for item in items:
                post = by_vk_id.get(int(item["id"]))
                if post is None:
                    continue
                stats = {
                    "views": (item.get("views") or {}).get("count", 0),
                    "likes": (item.get("likes") or {}).get("count", 0),
                    "comments": (item.get("comments") or {}).get("count", 0),
                    "reposts": (item.get("reposts") or {}).get("count", 0),
                }
                r = reach.get(post.vk_post_id)
                if r:
                    stats["reach"] = r.get("reach_total")
                    stats["clicks"] = r.get("links")
                    stats["joins"] = r.get("join_group")
                    stats["hides"] = r.get("hide")
                stats["collected_at"] = utcnow().isoformat()
                post.analytics = {**(post.analytics or {}), **stats}
                db.add(PostStatSnapshot(post_id=post.id, views=stats["views"], likes=stats["likes"],
                                        comments=stats["comments"], reposts=stats["reposts"],
                                        clicks=stats.get("clicks"), reach=stats.get("reach")))
                updated += 1
    db.flush()
    return updated


def collect_recent(db: Session, days: int | None = None) -> dict:
    since = utcnow() - timedelta(days=days or settings.ANALYTICS_COLLECT_DAYS)
    posts = list(db.execute(
        select(Post).where(Post.status == PostStatus.PUBLISHED.value, Post.published_at >= since,
                           Post.vk_post_id.is_not(None), Post.community_id.is_not(None))
    ).scalars())
    grouped: dict[int, list[Post]] = defaultdict(list)
    for post in posts:
        grouped[post.community_id].append(post)
    totals = {"communities": 0, "posts": 0, "errors": 0}
    for community_id, items in grouped.items():
        community = db.get(Community, community_id)
        try:
            totals["posts"] += collect_for_community(db, community, items)
            totals["communities"] += 1
            db.commit()
        except VKError as exc:
            db.rollback()
            totals["errors"] += 1
            syslog(db, LogLevel.WARNING, "analytics", f"Community #{community_id}: {exc}",
                   project_id=community.project_id if community else None)
            db.commit()
    return totals
