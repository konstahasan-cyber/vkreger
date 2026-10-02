from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int


class JobOut(ORMModel):
    id: int
    type: str
    status: str
    project_id: int | None
    params: dict[str, Any]
    result: dict[str, Any]
    error: str | None
    created_at: datetime
    updated_at: datetime


class Message(BaseModel):
    message: str
