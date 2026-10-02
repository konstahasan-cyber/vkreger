from __future__ import annotations

from app.db.session import SessionLocal, session_scope
from app.models.content import Post
from app.services.publishing_service import claim_due_posts, publish_claimed, recover_stuck
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.publishing.dispatch_due_posts")
def dispatch_due_posts() -> list[int]:
    db = SessionLocal()
    try:
        ids = claim_due_posts(db)
    finally:
        db.close()
    for post_id in ids:
        publish_post.delay(post_id)
    return ids


@celery_app.task(name="app.workers.tasks.publishing.publish_post")
def publish_post(post_id: int) -> str:
    with session_scope() as db:
        post = db.get(Post, post_id, with_for_update=True)
        if post is None:
            return "missing"
        if post.status != "publishing":
            return f"skipped ({post.status})"
        publish_claimed(db, post)
        return post.status


@celery_app.task(name="app.workers.tasks.publishing.recover_stuck_posts")
def recover_stuck_posts() -> list[int]:
    with session_scope() as db:
        return recover_stuck(db)
