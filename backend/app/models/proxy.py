from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import EncryptedText
from app.models.enums import ProxyScheme, ProxyStatus


class Proxy(TimestampMixin, Base):
    __tablename__ = "proxies"
    __table_args__ = (UniqueConstraint("scheme", "host", "port", "username", name="uq_proxies_endpoint"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme: Mapped[str] = mapped_column(String(16), default=ProxyScheme.HTTP.value)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    username: Mapped[str | None] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(EncryptedText)
    label: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[str] = mapped_column(String(16), default=ProxyStatus.UNKNOWN.value, index=True)
    external_ip: Mapped[str | None] = mapped_column(String(64))
    country: Mapped[str | None] = mapped_column(String(64))
    country_code: Mapped[str | None] = mapped_column(String(8))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)

    account = relationship("VKAccount", back_populates="proxy", uselist=False)

    def url(self) -> str:
        """Full proxy URL including credentials. Never log this value."""
        auth = ""
        if self.username:
            from urllib.parse import quote

            auth = quote(self.username, safe="")
            if self.password:
                auth += ":" + quote(self.password, safe="")
            auth += "@"
        # "HTTPS proxy" in provider lists means an HTTP proxy that supports CONNECT
        # (HTTPS tunnelling); httpx talks to such proxies via an "http://" URL.
        scheme = "socks5" if self.scheme == ProxyScheme.SOCKS5.value else "http"
        return f"{scheme}://{auth}{self.host}:{self.port}"

    def display(self) -> str:
        user = f"{self.username}@" if self.username else ""
        return f"{self.scheme}://{user}{self.host}:{self.port}"
