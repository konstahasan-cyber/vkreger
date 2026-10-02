from __future__ import annotations

from sqlalchemy import select

from app.db.session import session_scope
from app.models.community import Community
from app.models.enums import EventMode, LogLevel, ReplyStatus
from app.models.inbox import InboxItem
from app.services.audit import syslog
from app.services.inbox_service import poll_longpoll, triage_item
from app.vk.errors import VKError
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.inbox.triage")
def triage(item_id: int) -> str | None:
    with session_scope() as db:
        item = db.get(InboxItem, item_id)
        if item is None or item.reply_status != ReplyStatus.NEW.value:
            return None
        triage_item(db, item)
        return item.classification


@celery_app.task(name="app.workers.tasks.inbox.triage_pending")
def triage_pending() -> int:
    """Safety net: triage items whose immediate task was lost."""
    with session_scope() as db:
        ids = list(db.execute(select(InboxItem.id).where(InboxItem.reply_status == ReplyStatus.NEW.value,
                                                         InboxItem.error.is_(None)).limit(50)).scalars())
    for item_id in ids:
        triage(item_id)
    return len(ids)


@celery_app.task(name="app.workers.tasks.inbox.longpoll_cycle")
def longpoll_cycle() -> dict:
    stored = {}
    with session_scope() as db:
        communities = list(db.execute(select(Community).where(Community.event_mode == EventMode.LONGPOLL.value)).scalars())
        for community in communities:
            try:
                stored[community.id] = poll_longpoll(db, community, wait=10)
                db.commit()
            except VKError as exc:
                db.rollback()
                syslog(db, LogLevel.WARNING, "longpoll", f"Community #{community.id}: {exc}",
                       project_id=community.project_id)
                db.commit()
    if any(stored.values()):
        triage_pending.delay()
    return stored
