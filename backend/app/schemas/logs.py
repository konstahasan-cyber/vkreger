from __future__ import annotations

from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class SystemLogOut(ORMModel):
    id: int
    level: str
    source: str
    message: str
    context: dict[str, Any]
    project_id: int | None
    created_at: datetime


class AuditLogOut(ORMModel):
    id: int
    user_id: int | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict[str, Any]
    ip: str | None
    created_at: datetime


class AIUsageOut(ORMModel):
    id: int
    model: str
    operation: str
    agent: str | None
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    images: int
    estimated_cost: float
    project_id: int | None
    success: bool
    automatic: bool
    created_at: datetime
