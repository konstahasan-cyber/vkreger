from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.enums import ReplyStatus
from app.models.inbox import InboxItem, Lead
from app.models.system import Notification
from app.models.user import User
from app.schemas.common import Page
from app.schemas.inbox import InboxItemOut, LeadCreate, LeadOut, LeadUpdate, NotificationOut, ReplyRequest
from app.services.audit import audit
from app.services.inbox_service import claim_for_triage, send_reply, triage_item

router = APIRouter(tags=["inbox"])


def _item(db: Session, item_id: int) -> InboxItem:
    item = db.get(InboxItem, item_id)
    if item is None:
        raise HTTPException(404, "Сообщение не найдено")
    return item


@router.get("/messages", response_model=Page[InboxItemOut])
def list_messages(project_id: int | None = None, classification: str | None = None, reply_status: str | None = None,
                  kind: str | None = None, limit: int = 50, offset: int = 0, db: Session = Depends(get_db),
                  _: User = Depends(require(Permission.VIEW))) -> Page[InboxItemOut]:
    query = select(InboxItem)
    if project_id:
        query = query.where(InboxItem.project_id == project_id)
    if classification:
        query = query.where(InboxItem.classification == classification)
    if reply_status:
        query = query.where(InboxItem.reply_status.in_(reply_status.split(",")))
    if kind:
        query = query.where(InboxItem.kind == kind)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(InboxItem.id.desc()).limit(min(limit, 200)).offset(offset)).scalars()
    return Page(items=[InboxItemOut.model_validate(r) for r in rows], total=total)


@router.post("/messages/{item_id}/reply", response_model=InboxItemOut)
def reply(item_id: int, body: ReplyRequest, request: Request, db: Session = Depends(get_db),
          user: User = Depends(require(Permission.HANDLE_INBOX))) -> InboxItem:
    """Send the operator-approved reply (edited text or the AI suggestion as is)."""
    item = _item(db, item_id)
    text = body.text or item.suggested_reply
    if not text:
        raise HTTPException(422, "Нет текста ответа")
    send_reply(db, item, text, user_id=user.id)
    audit(db, user.id, "inbox.reply", "inbox_item", item.id, {"status": item.reply_status}, client_ip(request))
    db.commit()
    return item


@router.post("/messages/{item_id}/reject", response_model=InboxItemOut)
def reject(item_id: int, db: Session = Depends(get_db), user: User = Depends(require(Permission.HANDLE_INBOX))) -> InboxItem:
    item = _item(db, item_id)
    item.reply_status = ReplyStatus.REJECTED.value
    item.handled_by = user.id
    db.commit()
    return item


@router.post("/messages/{item_id}/triage", response_model=InboxItemOut)
def retriage(item_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.HANDLE_INBOX))) -> InboxItem:
    item = _item(db, item_id)
    if item.reply_status == ReplyStatus.SENT.value:
        raise HTTPException(409, "Уже отвечено")
    if not claim_for_triage(db, item.id, manual=True):
        raise HTTPException(409, "Сообщение сейчас обрабатывается")
    db.refresh(item)
    triage_item(db, item, automatic=False)
    db.commit()
    return item


@router.get("/leads", response_model=Page[LeadOut])
def list_leads(project_id: int | None = None, status: str | None = None, limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> Page[LeadOut]:
    query = select(Lead)
    if project_id:
        query = query.where(Lead.project_id == project_id)
    if status:
        query = query.where(Lead.status == status)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(Lead.id.desc()).limit(min(limit, 200)).offset(offset)).scalars()
    return Page(items=[LeadOut.model_validate(r) for r in rows], total=total)


@router.post("/leads", response_model=LeadOut, status_code=201)
def create_lead(body: LeadCreate, db: Session = Depends(get_db), _: User = Depends(require(Permission.HANDLE_INBOX))) -> Lead:
    lead = Lead(**body.model_dump(), data={"source": "manual"})
    db.add(lead)
    db.commit()
    return lead


@router.patch("/leads/{lead_id}", response_model=LeadOut)
def update_lead(lead_id: int, body: LeadUpdate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.HANDLE_INBOX))) -> Lead:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, "Заявка не найдена")
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(lead, key, value.value if hasattr(value, "value") else value)
    audit(db, user.id, "lead.update", "lead", lead.id, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return lead


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(unread: bool = False, db: Session = Depends(get_db),
                  _: User = Depends(require(Permission.VIEW))) -> list[Notification]:
    query = select(Notification)
    if unread:
        query = query.where(Notification.is_read.is_(False))
    return list(db.execute(query.order_by(Notification.id.desc()).limit(100)).scalars())


@router.post("/notifications/read-all", status_code=204)
def read_all(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> None:
    db.execute(update(Notification).where(Notification.is_read.is_(False)).values(is_read=True))
    db.commit()
