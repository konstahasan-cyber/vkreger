from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import ImageFormat
from app.schemas.common import ORMModel


class PostOut(ORMModel):
    id: int
    project_id: int
    community_id: int | None
    title: str | None
    text: str
    attachments: list[Any]
    category: str | None
    topic: str | None
    cta: str | None
    hashtags: list[str]
    scheduled_at: datetime | None
    published_at: datetime | None
    status: str
    vk_post_id: int | None
    attempts: int
    last_error: str | None
    is_pinned: bool
    image_prompt: str | None
    image_format: str
    image_url: str | None = None
    generation_metadata: dict[str, Any]
    analytics: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_model(cls, post) -> PostOut:  # noqa: ANN001
        out = cls.model_validate(post)
        if post.image_path:
            import os

            out.image_url = f"/media/{post.project_id}/{os.path.basename(post.image_path)}"
        return out


class PostCreate(BaseModel):
    project_id: int
    title: str | None = None
    text: str = Field(min_length=1, max_length=16000)
    category: str | None = None
    attachments: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None


class PostUpdate(BaseModel):
    title: str | None = None
    text: str | None = Field(default=None, max_length=16000)
    category: str | None = None
    attachments: list[str] | None = None
    image_prompt: str | None = None
    image_format: ImageFormat | None = None
    cta: str | None = None


class GeneratePostsRequest(BaseModel):
    project_id: int
    count: int = Field(default=1, ge=1, le=20)
    topic: str | None = None
    rubric_code: str | None = None
    angle: str | None = None
    instructions: str | None = Field(default=None, max_length=2000)
    with_image: bool | None = None
    force: bool = False


class ScheduleRequest(BaseModel):
    scheduled_at: datetime | None = None


class ImageRequest(BaseModel):
    image_format: ImageFormat | None = None
    image_prompt: str | None = None
    force: bool = False


class FillQueueRequest(BaseModel):
    horizon_days: int | None = Field(default=None, ge=1, le=30)
    max_new: int = Field(default=5, ge=1, le=30)
    force: bool = False
