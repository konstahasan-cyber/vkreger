from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import JSONType
from app.models.enums import ImageFormat, PlanItemStatus, PostStatus


class Rubric(TimestampMixin, Base):
    __tablename__ = "rubrics"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_rubrics_project_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    project = relationship("Project", back_populates="rubrics")


class Strategy(TimestampMixin, Base):
    __tablename__ = "strategies"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(32), default="setup")  # setup | analyst | manual
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    reasoning: Mapped[str | None] = mapped_column(Text)


class ContentPlanItem(TimestampMixin, Base):
    __tablename__ = "content_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    rubric_code: Mapped[str] = mapped_column(String(64))
    topic: Mapped[str] = mapped_column(Text)
    angle: Mapped[str | None] = mapped_column(Text)
    planned_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=PlanItemStatus.PLANNED.value, index=True)
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id", ondelete="SET NULL"))


class Post(TimestampMixin, Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    community_id: Mapped[int | None] = mapped_column(ForeignKey("communities.id", ondelete="SET NULL"), index=True)
    title: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list] = mapped_column(JSONType, default=list)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    topic: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list] = mapped_column(JSONType, default=list)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=PostStatus.DRAFT.value, index=True)
    vk_post_id: Mapped[int | None] = mapped_column(BigInteger)
    # Idempotency key sent to VK wall.post as `guid` — prevents duplicate publications on retries.
    guid: Mapped[str] = mapped_column(String(64), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    publishing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    image_prompt: Mapped[str | None] = mapped_column(Text)
    image_format: Mapped[str] = mapped_column(String(16), default=ImageFormat.NONE.value)
    image_path: Mapped[str | None] = mapped_column(String(512))

    generation_metadata: Mapped[dict] = mapped_column(JSONType, default=dict)
    analytics: Mapped[dict] = mapped_column(JSONType, default=dict)
    embedding: Mapped[list | None] = mapped_column(JSONType, nullable=True, deferred=True)

    community = relationship("Community")
