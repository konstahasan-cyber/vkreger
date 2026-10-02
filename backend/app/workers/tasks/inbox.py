from __future__ import annotations

from sqlalchemy import select

from app.db.session import session_scope
from app.models.community import Community
from app.models.enums import EventMode, LogLevel, ReplyStatus
from app.models.inbox import InboxItem
from app.services.audit import syslog
from app.services.inbox_service import claim_for_triage, pending_triage_ids, poll_longpoll, triage_item
from app.vk.errors import VKError
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.inbox.triage")
def triage(item_id: int) -> str | None:
    with session_scope() as db:
        if not claim_for_triage(db, item_id):
            return None  # already being processed / processed by another run
        item = db.get(InboxItem, item_id)
        try:
            triage_item(db, item)
        except Exception as exc:
            db.rollback()
            item = db.get(InboxItem, item_id)
            item.reply_status = ReplyStatus.FAILED.value
            item.error = f"triage failed: {type(exc).__name__}: {exc}"[:1000]
            syslog(db, LogLevel.ERROR, "inbox", f"Triage of inbox item #{item_id} crashed: {exc}",
                   project_id=item.project_id)
            return None
        return item.classification


@celery_app.task(name="app.workers.tasks.inbox.triage_pending")
def triage_pending() -> int:
    """Safety net: triage items whose immediate task was lost or postponed by the cost limit."""
    with session_scope() as db:
        ids = pending_triage_ids(db)
    for item_id in ids:
        triage(item_id)  # each item is isolated: triage() never raises
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
