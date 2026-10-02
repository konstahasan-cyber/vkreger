from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import LeadStatus
from app.schemas.common import ORMModel


class InboxItemOut(ORMModel):
    id: int
    project_id: int | None
    community_id: int
    kind: str
    vk_item_id: int
    vk_post_id: int | None
    peer_id: int | None
    from_id: int | None
    text: str
    classification: str | None
    confidence: float | None
    suggested_reply: str | None
    reply_text: str | None
    reply_status: str
    sent_at: datetime | None
    error: str | None
    created_at: datetime


class ReplyRequest(BaseModel):
    text: str | None = Field(default=None, max_length=4000)


class LeadOut(ORMModel):
    id: int
    project_id: int | None
    inbox_item_id: int | None
    vk_user_id: int | None
    name: str | None
    contact: str | None
    need: str | None
    status: str
    notes: str | None
    data: dict[str, Any]
    created_at: datetime


class LeadUpdate(BaseModel):
    name: str | None = None
    contact: str | None = None
    need: str | None = None
    status: LeadStatus | None = None
    notes: str | None = None


class LeadCreate(BaseModel):
    project_id: int
    name: str | None = None
    contact: str | None = None
    need: str | None = None
    vk_user_id: int | None = None
    notes: str | None = None


class NotificationOut(ORMModel):
    id: int
    kind: str
    title: str
    body: str | None
    project_id: int | None
    link: str | None
    is_read: bool
    created_at: datetime
