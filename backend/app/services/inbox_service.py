"""Incoming comments/messages: storage, AI triage, replies, leads, operator notifications."""
from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import CostLimitExceeded, ValidationAppError
from app.db.base import utcnow
from app.models.community import Community
from app.models.content import Post
from app.models.enums import AutoReplyMode, InboxClass, InboxKind, LeadStatus, LogLevel, ReplyStatus
from app.models.inbox import InboxItem, Lead
from app.models.system import Notification
from app.openai.agents import community_manager
from app.openai.provider import AIError
from app.openai.service import AIService
from app.services.audit import syslog
from app.vk.errors import VKError
from app.vk.factory import client_for_community

logger = logging.getLogger(__name__)

NEVER_AUTO = {InboxClass.NEGATIVE.value, InboxClass.SPAM.value}


def ingest_event(db: Session, community: Community, event: dict) -> InboxItem | None:
    """Store a VK event (Callback API / Long Poll). Returns the new item or None (ignored/duplicate)."""
    etype = event.get("type")
    obj = event.get("object") or {}
    if etype == "message_new":
        message = obj.get("message", obj)
        if int(message.get("from_id", 0)) < 0 or message.get("out"):
            return None
        item = InboxItem(kind=InboxKind.MESSAGE.value, vk_item_id=int(message.get("id") or message.get("conversation_message_id") or 0),
                         peer_id=message.get("peer_id"), from_id=message.get("from_id"), text=message.get("text") or "")
    elif etype == "wall_reply_new":
        if int(obj.get("from_id", 0)) == -abs(community.vk_group_id):
            return None  # our own reply
        item = InboxItem(kind=InboxKind.COMMENT.value, vk_item_id=int(obj["id"]), vk_post_id=obj.get("post_id"),
                         from_id=obj.get("from_id"), text=obj.get("text") or "")
    else:
        return None
    if not item.text.strip():
        return None
    item.community_id = community.id
    item.project_id = community.project_id
    item.raw = {"type": etype, "event_id": event.get("event_id")}
    item.reply_status = ReplyStatus.NEW.value
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        return None  # VK re-delivered the same event
    return item


def notify_operator(db: Session, *, kind: str, title: str, body: str, project_id: int | None, link: str | None = None) -> None:
    db.add(Notification(kind=kind, title=title, body=body, project_id=project_id, link=link))
    if settings.OPERATOR_WEBHOOK_URL:
        try:
            httpx.post(settings.OPERATOR_WEBHOOK_URL, json={"kind": kind, "title": title, "body": body,
                                                           "project_id": project_id, "link": link}, timeout=5)
        except httpx.HTTPError as exc:
            logger.warning("Operator webhook failed: %s", type(exc).__name__)


def triage_item(db: Session, item: InboxItem, *, automatic: bool = True) -> InboxItem:
    community = db.get(Community, item.community_id)
    project = community.project if community else None
    if project is None:
        item.reply_status = ReplyStatus.IGNORED.value
        item.error = "community is not connected to a project"
        db.flush()
        return item
    context_hint = None
    if item.kind == InboxKind.COMMENT.value and item.vk_post_id:
        post = db.execute(select(Post).where(Post.community_id == community.id, Post.vk_post_id == item.vk_post_id)).scalar_one_or_none()
        context_hint = post.title if post else None
    try:
        data = community_manager.triage(AIService(db), project, kind=item.kind, text=item.text,
                                        context_hint=context_hint, automatic=automatic)
    except (CostLimitExceeded, AIError) as exc:
        item.error = str(exc)
        syslog(db, LogLevel.WARNING, "inbox", f"Triage of inbox item #{item.id} skipped: {exc}", project_id=project.id)
        db.flush()
        return item
    item.classification = data.get("classification", InboxClass.OTHER.value)
    item.confidence = float(data.get("confidence") or 0)
    item.suggested_reply = data.get("reply")

    if item.classification == InboxClass.LEAD.value:
        lead_data = data.get("lead") or {}
        lead = Lead(project_id=project.id, inbox_item_id=item.id, vk_user_id=item.from_id, name=lead_data.get("name"),
                    contact=lead_data.get("contact"), need=lead_data.get("need") or item.text[:500],
                    status=LeadStatus.NEW.value, data={"source": item.kind})
        db.add(lead)
        db.flush()
        notify_operator(db, kind="lead", title=f"Новый лид: {project.name}", body=item.text[:500],
                        project_id=project.id, link=f"/leads?id={lead.id}")
    elif item.classification == InboxClass.NEGATIVE.value or data.get("needs_operator"):
        notify_operator(db, kind="attention", title=f"Требуется оператор: {project.name}", body=item.text[:500],
                        project_id=project.id, link="/messages")

    mode = project.auto_reply_mode
    if item.classification == InboxClass.SPAM.value or not item.suggested_reply:
        item.reply_status = ReplyStatus.IGNORED.value if item.classification == InboxClass.SPAM.value else ReplyStatus.SUGGESTED.value
    elif mode == AutoReplyMode.OFF.value:
        item.reply_status = ReplyStatus.SUGGESTED.value
    elif (mode == AutoReplyMode.AUTO.value and item.classification in (project.auto_reply_types or [])
          and item.classification not in NEVER_AUTO):
        db.flush()
        send_reply(db, item, item.suggested_reply, user_id=None)
    else:
        item.reply_status = ReplyStatus.PENDING_APPROVAL.value
    db.flush()
    return item


def send_reply(db: Session, item: InboxItem, text: str, *, user_id: int | None) -> InboxItem:
    if not text or not text.strip():
        raise ValidationAppError("Reply text is empty")
    if item.reply_status == ReplyStatus.SENT.value:
        raise ValidationAppError("Reply already sent")
    community = db.get(Community, item.community_id)
    try:
        if item.kind == InboxKind.COMMENT.value:
            with client_for_community(community) as client:
                item.reply_vk_id = client.create_comment(community.vk_group_id, int(item.vk_post_id), text,
                                                         reply_to_comment=item.vk_item_id)
        else:
            if not community.community_token:
                raise ValidationAppError("Sending messages requires a community access token")
            with client_for_community(community) as client:
                item.reply_vk_id = client.send_message(int(item.peer_id or item.from_id), text,
                                                       group_id=community.vk_group_id)
    except VKError as exc:
        item.reply_status = ReplyStatus.FAILED.value
        item.error = str(exc)[:1000]
        syslog(db, LogLevel.ERROR, "inbox", f"Reply to inbox item #{item.id} failed: {exc}", project_id=item.project_id)
        db.flush()
        return item
    item.reply_text = text
    item.reply_status = ReplyStatus.SENT.value
    item.sent_at = utcnow()
    item.handled_by = user_id
    item.error = None
    db.flush()
    return item


def poll_longpoll(db: Session, community: Community, wait: int = 20) -> int:
    """One Bots Long Poll API cycle for a community. Returns number of stored items."""
    with client_for_community(community) as client:
        server = community.longpoll_server or {}
        if not server.get("server"):
            server = client.get_long_poll_server(community.vk_group_id)
        data = client.raw_get(server["server"], {"act": "a_check", "key": server["key"], "ts": server["ts"],
                                                 "wait": wait}, timeout=wait + 10)
    if "failed" in data:
        if data["failed"] == 1:
            server["ts"] = data["ts"]
        else:
            server = {}  # key expired / info lost → re-request server next time
        community.longpoll_server = server
        db.flush()
        return 0
    server["ts"] = data["ts"]
    community.longpoll_server = dict(server)
    stored = 0
    for event in data.get("updates", []):
        if ingest_event(db, community, event):
            stored += 1
    db.flush()
    return stored
