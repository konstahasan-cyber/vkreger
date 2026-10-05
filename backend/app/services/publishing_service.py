"""Publishing pipeline with retries and duplicate protection.

Duplicate protection layers:
1. Atomic claim: only one worker can move a post from ``scheduled`` to ``publishing``.
2. ``vk_post_id`` present → never post again.
3. ``wall.post`` is called with ``guid=post.guid`` — VK refuses to create a second post
   with the same guid.
4. Posts stuck in ``publishing`` are reconciled against ``wall.get`` before re-queueing.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ValidationAppError
from app.db.base import utcnow
from app.models.content import Post
from app.models.enums import LogLevel, PostStatus
from app.services.audit import syslog
from app.vk.errors import ProxyUnavailableError, VKAPIError, VKError, VKNetworkError
from app.vk.factory import run_for_community

logger = logging.getLogger(__name__)

PUBLISHABLE_FROM = {PostStatus.DRAFT.value, PostStatus.APPROVED.value, PostStatus.SCHEDULED.value,
                    PostStatus.FAILED.value}


def build_message(post: Post) -> str:
    return post.text.strip()


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, VKAPIError):
        return exc.retryable
    if isinstance(exc, ProxyUnavailableError):
        return True  # proxy may be replaced by the next health check
    return isinstance(exc, (VKNetworkError, OSError))


def claim_due_posts(db: Session, now: datetime | None = None, limit: int = 100) -> list[int]:
    """Atomically move due scheduled posts to ``publishing`` and return their ids."""
    now = now or utcnow()
    ids = list(db.execute(
        select(Post.id)
        .where(Post.status == PostStatus.SCHEDULED.value, Post.scheduled_at <= now)
        .order_by(Post.scheduled_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).scalars())
    if not ids:
        return []
    result = db.execute(
        update(Post)
        .where(Post.id.in_(ids), Post.status == PostStatus.SCHEDULED.value)
        .values(status=PostStatus.PUBLISHING.value, publishing_started_at=now)
        .returning(Post.id)
    )
    claimed = [row[0] for row in result]
    db.commit()
    return claimed


def claim_post(db: Session, post_id: int) -> bool:
    result = db.execute(
        update(Post)
        .where(Post.id == post_id, Post.status.in_(PUBLISHABLE_FROM))
        .values(status=PostStatus.PUBLISHING.value, publishing_started_at=utcnow())
    )
    db.flush()
    return result.rowcount == 1


def _upload_image(client, post: Post) -> None:  # noqa: ANN001
    if not post.image_path or any(str(a).startswith("photo") for a in post.attachments or []):
        return
    path = Path(post.image_path)
    if not path.exists():
        syslog(post_db(post), LogLevel.WARNING, "publishing", f"Image file missing for post #{post.id}",
               project_id=post.project_id)
        return
    attachment = client.upload_wall_photo(post.community.vk_group_id, path.read_bytes(), path.name)
    # persisted immediately so a retry doesn't upload the photo again
    post.attachments = [attachment, *[a for a in post.attachments or [] if not str(a).startswith("photo")]]


def post_db(post: Post) -> Session:
    from sqlalchemy.orm import object_session

    return object_session(post)  # type: ignore[return-value]


def _do_publish(db: Session, post: Post) -> None:
    community = post.community
    if community is None:
        raise ValidationAppError(f"У поста #{post.id} нет сообщества")
    def op(client):  # noqa: ANN001, ANN202
        try:
            _upload_image(client, post)
        except VKAPIError as exc:
            # Community keys can't upload wall photos (error 27). Without an account to fall back
            # to, publish the text instead of failing the whole post.
            if community.account is not None or exc.code not in (7, 15, 27):
                raise
            meta = dict(post.generation_metadata or {})
            meta["image_skipped"] = f"VK не дал загрузить картинку ключом сообщества (ошибка {exc.code})"
            post.generation_metadata = meta
            syslog(db, LogLevel.WARNING, "publishing",
                   f"Post #{post.id}: image skipped — community key can't upload photos (VK error {exc.code}). "
                   "Add a VK account to publish images.", project_id=post.project_id)
        db.flush()
        return client.wall_post(community.vk_group_id, build_message(post),
                                attachments=post.attachments or None, guid=post.guid)

    post.vk_post_id = run_for_community(community, op)


def publish_claimed(db: Session, post: Post) -> Post:
    """Publish a post already in ``publishing`` state. Handles errors/retries."""
    if post.vk_post_id:
        post.status = PostStatus.PUBLISHED.value
        post.published_at = post.published_at or utcnow()
        db.flush()
        return post
    post.attempts = (post.attempts or 0) + 1
    try:
        _do_publish(db, post)
    except (VKError, ValidationAppError, OSError, ValueError, KeyError, TypeError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        post.last_error = message[:2000]
        retry = _is_retryable(exc) and post.attempts < settings.PUBLISH_MAX_ATTEMPTS
        if retry:
            delay = settings.PUBLISH_RETRY_BASE_SECONDS * (2 ** (post.attempts - 1))
            post.status = PostStatus.SCHEDULED.value
            post.scheduled_at = utcnow() + timedelta(seconds=delay)
        else:
            post.status = PostStatus.FAILED.value
        syslog(db, LogLevel.ERROR, "publishing",
               f"Post #{post.id} publish attempt {post.attempts} failed: {message}"
               + (f"; retry in {delay}s" if retry else "; giving up"),
               project_id=post.project_id, context={"post_id": post.id, "attempt": post.attempts})
        db.flush()
        return post
    post.status = PostStatus.PUBLISHED.value
    post.published_at = utcnow()
    post.last_error = None
    syslog(db, LogLevel.INFO, "publishing", f"Post #{post.id} published as wall post {post.vk_post_id}",
           project_id=post.project_id)
    db.flush()
    return post


def publish_post_now(db: Session, post: Post) -> Post:
    if post.status == PostStatus.PUBLISHED.value:
        return post
    if not claim_post(db, post.id):
        raise ValidationAppError(f"Пост #{post.id} нельзя опубликовать из статуса «{post.status}»")
    db.refresh(post)
    return publish_claimed(db, post)


def recover_stuck(db: Session) -> list[int]:
    """Reconcile posts stuck in ``publishing`` (worker crash) without creating duplicates."""
    threshold = utcnow() - timedelta(minutes=settings.PUBLISH_STUCK_MINUTES)
    stuck = list(db.execute(
        select(Post).where(Post.status == PostStatus.PUBLISHING.value, Post.publishing_started_at < threshold)
    ).scalars())
    recovered = []
    for post in stuck:
        if post.vk_post_id:
            post.status = PostStatus.PUBLISHED.value
            post.published_at = post.published_at or utcnow()
            recovered.append(post.id)
            continue
        found_id = None
        if post.community is not None:
            try:
                wall = run_for_community(post.community, lambda c, gid=post.community.vk_group_id: c.wall_get(gid, count=30))
                body = build_message(post).strip()
                for item in wall:
                    if (item.get("text") or "").strip() == body:
                        found_id = int(item["id"])
                        break
            except (VKError, ValueError, KeyError) as exc:
                syslog(db, LogLevel.WARNING, "publishing", f"Cannot reconcile post #{post.id}: {exc}",
                       project_id=post.project_id)
                continue
        if found_id:
            post.vk_post_id = found_id
            post.status = PostStatus.PUBLISHED.value
            post.published_at = utcnow()
        else:
            post.status = PostStatus.SCHEDULED.value
            post.scheduled_at = utcnow()
        recovered.append(post.id)
        syslog(db, LogLevel.WARNING, "publishing",
               f"Recovered stuck post #{post.id}: {'found on wall' if found_id else 're-queued'}",
               project_id=post.project_id)
    db.flush()
    return recovered


def schedule_post(db: Session, post: Post, when: datetime | None) -> Post:
    if post.status in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value):
        raise ValidationAppError(f"Пост #{post.id} уже в статусе «{post.status}»")
    if post.community_id is None:
        raise ValidationAppError("Сначала подключите сообщество к проекту")
    if when is None:
        from app.content.slots import free_slots

        slots = free_slots(db, post_project(db, post), 1)
        if not slots:
            raise ValidationAppError("Нет свободного времени для публикации в ближайшие дни")
        when = slots[0]
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    post.scheduled_at = when
    post.status = PostStatus.SCHEDULED.value
    post.last_error = None
    db.flush()
    return post


def post_project(db: Session, post: Post):  # noqa: ANN201
    from app.models.project import Project

    return db.get(Project, post.project_id)
