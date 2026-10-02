from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class AccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    access_token: str = Field(min_length=10, max_length=4096)
    proxy_id: int | None = None
    auto_replace_proxy: bool = True


class AccountUpdate(BaseModel):
    name: str | None = None
    access_token: str | None = Field(default=None, min_length=10, max_length=4096)
    auto_replace_proxy: bool | None = None
    status: str | None = None


class AccountProxyUpdate(BaseModel):
    proxy_id: int | None


class AccountOut(ORMModel):
    id: int
    name: str
    vk_user_id: int | None
    status: str
    last_checked_at: datetime | None
    last_error: str | None
    proxy_id: int | None
    proxy_display: str | None = None
    proxy_status: str | None = None
    auto_replace_proxy: bool
    info: dict[str, Any]
    groups_cache: list[dict[str, Any]]
    token_masked: str = "********"
    created_at: datetime

    @classmethod
    def from_model(cls, account) -> AccountOut:  # noqa: ANN001
        out = cls.model_validate(account)
        if account.proxy is not None:
            out.proxy_display = account.proxy.display()
            out.proxy_status = account.proxy.status
        return out
