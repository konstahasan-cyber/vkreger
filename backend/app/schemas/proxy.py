from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.crypto import mask_secret
from app.models.enums import ProxyScheme
from app.schemas.common import ORMModel


class ProxyImport(BaseModel):
    text: str = Field(min_length=1, max_length=500_000)
    default_scheme: ProxyScheme = ProxyScheme.HTTP
    check: bool = True


class ProxyUpdate(BaseModel):
    label: str | None = None
    password: str | None = None
    scheme: ProxyScheme | None = None


class ProxyOut(ORMModel):
    id: int
    scheme: str
    host: str
    port: int
    username: str | None
    password_masked: str | None = None
    label: str | None
    status: str
    external_ip: str | None
    country: str | None
    country_code: str | None
    latency_ms: int | None
    last_checked_at: datetime | None
    last_error: str | None
    account_id: int | None = None
    account_name: str | None = None

    @classmethod
    def from_model(cls, proxy) -> ProxyOut:  # noqa: ANN001
        out = cls.model_validate(proxy)
        out.password_masked = mask_secret(proxy.password)  # never the full password
        if proxy.account is not None:
            out.account_id = proxy.account.id
            out.account_name = proxy.account.name
        return out


class ProxyImportResult(BaseModel):
    created: list[int]
    skipped_duplicates: int
    errors: list[dict]
    check_job: str | None = None
