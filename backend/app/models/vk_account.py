from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import EncryptedText, JSONType
from app.models.enums import AccountStatus


class VKAccount(TimestampMixin, Base):
    __tablename__ = "vk_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    vk_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    access_token: Mapped[str] = mapped_column(EncryptedText)
    status: Mapped[str] = mapped_column(String(16), default=AccountStatus.NEW.value, index=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    # unique => one proxy can belong to at most one account
    proxy_id: Mapped[int | None] = mapped_column(
        ForeignKey("proxies.id", ondelete="SET NULL"), unique=True, nullable=True
    )
    auto_replace_proxy: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cached profile data: first/last name, photo, token scope, etc.
    info: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Cached communities administered by the account: [{id, name, screen_name, ...}]
    groups_cache: Mapped[list] = mapped_column(JSONType, default=list)

    proxy = relationship("Proxy", back_populates="account")
    communities = relationship("Community", back_populates="account")

    def __repr__(self) -> str:  # never include the token
        return f"<VKAccount id={self.id} vk_user_id={self.vk_user_id} status={self.status}>"
