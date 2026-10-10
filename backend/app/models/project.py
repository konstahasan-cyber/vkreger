from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.db.types import JSONType
from app.models.enums import AutoReplyMode, ImageFormat, ProjectGoal, ProjectStatus, Tone


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    business_name: Mapped[str] = mapped_column(String(255))
    theme: Mapped[str | None] = mapped_column(String(255))
    niche: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(255))
    target_audience: Mapped[str | None] = mapped_column(Text)
    product_description: Mapped[str | None] = mapped_column(Text)
    advantages: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(512))
    contacts: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(String(32), default=ProjectGoal.LEADS.value)
    posts_per_day: Mapped[int | None] = mapped_column(Integer)
    posts_per_week: Mapped[int | None] = mapped_column(Integer, default=7)
    tone: Mapped[str] = mapped_column(String(32), default=Tone.FRIENDLY.value)
    custom_tone_prompt: Mapped[str | None] = mapped_column(Text)

    vk_account_id: Mapped[int | None] = mapped_column(ForeignKey("vk_accounts.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ProjectStatus.DRAFT.value, index=True)
    # Groups on the same topic share a network: posts are checked for repeats across the whole network
    network: Mapped[str | None] = mapped_column(String(255), index=True)

    # AI artefacts (compact, re-used as context instead of the whole history)
    setup_proposal: Mapped[dict] = mapped_column(JSONType, default=dict)
    context_summary: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[dict] = mapped_column(JSONType, default=dict)
    content_rules: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Scheduling
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    posting_times: Mapped[list] = mapped_column(JSONType, default=lambda: ["10:00", "19:00"])
    autopilot: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False)

    # Images
    images_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    image_format: Mapped[str] = mapped_column(String(16), default=ImageFormat.SQUARE.value)

    # Inbox
    auto_reply_mode: Mapped[str] = mapped_column(String(16), default=AutoReplyMode.APPROVAL.value)
    auto_reply_types: Mapped[list] = mapped_column(JSONType, default=lambda: ["QUESTION"])

    vk_account = relationship("VKAccount")
    community = relationship("Community", back_populates="project", uselist=False)
    rubrics = relationship("Rubric", back_populates="project", cascade="all, delete-orphan")
