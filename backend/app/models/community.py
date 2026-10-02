from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import EncryptedText, JSONType
from app.models.enums import EventMode


class Community(TimestampMixin, Base):
    __tablename__ = "communities"

    id: Mapped[int] = mapped_column(primary_key=True)
    vk_group_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    screen_name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(Text)
    members_count: Mapped[int | None] = mapped_column(Integer)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_app: Mapped[bool] = mapped_column(Boolean, default=False)

    account_id: Mapped[int | None] = mapped_column(ForeignKey("vk_accounts.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    # Community access token (from community settings → API) — needed for messages and Long Poll.
    community_token: Mapped[str | None] = mapped_column(EncryptedText)
    event_mode: Mapped[str] = mapped_column(String(16), default=EventMode.NONE.value)
    callback_secret: Mapped[str | None] = mapped_column(EncryptedText)
    confirmation_code: Mapped[str | None] = mapped_column(String(64))
    callback_server_id: Mapped[int | None] = mapped_column(Integer)
    longpoll_server: Mapped[dict] = mapped_column(JSONType, default=dict)
    pinned_post_id: Mapped[int | None] = mapped_column(BigInteger)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)

    account = relationship("VKAccount", back_populates="communities")
    project = relationship("Project", back_populates="community")
