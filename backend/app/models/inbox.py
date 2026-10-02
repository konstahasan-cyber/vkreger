from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.db.types import JSONType
from app.models.enums import LeadStatus, ReplyStatus


class InboxItem(TimestampMixin, Base):
    __tablename__ = "inbox_items"
    __table_args__ = (
        UniqueConstraint("community_id", "kind", "vk_item_id", name="uq_inbox_items_vk_item"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    community_id: Mapped[int] = mapped_column(ForeignKey("communities.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # comment | message
    vk_item_id: Mapped[int] = mapped_column(BigInteger)  # comment id or message id
    vk_post_id: Mapped[int | None] = mapped_column(BigInteger)  # for comments
    peer_id: Mapped[int | None] = mapped_column(BigInteger)  # for messages
    from_id: Mapped[int | None] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text, default="")
    raw: Mapped[dict] = mapped_column(JSONType, default=dict)

    classification: Mapped[str | None] = mapped_column(String(16), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    suggested_reply: Mapped[str | None] = mapped_column(Text)
    reply_text: Mapped[str | None] = mapped_column(Text)
    reply_status: Mapped[str] = mapped_column(String(32), default=ReplyStatus.NEW.value, index=True)
    reply_vk_id: Mapped[int | None] = mapped_column(BigInteger)
    handled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    inbox_item_id: Mapped[int | None] = mapped_column(ForeignKey("inbox_items.id", ondelete="SET NULL"))
    vk_user_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(255))
    contact: Mapped[str | None] = mapped_column(String(255))
    need: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=LeadStatus.NEW.value, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
