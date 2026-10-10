from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.models.enums import AutoReplyMode, EventMode, ImageFormat, InboxClass, ProjectGoal, Tone
from app.schemas.common import ORMModel


class ProjectBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    business_name: str = Field(min_length=1, max_length=255)
    theme: str | None = None
    niche: str | None = None
    city: str | None = None
    target_audience: str | None = None
    product_description: str | None = None
    advantages: str | None = None
    website: str | None = None
    contacts: str | None = None
    goal: ProjectGoal = ProjectGoal.LEADS
    posts_per_day: int | None = Field(default=None, ge=1, le=20)
    posts_per_week: int | None = Field(default=7, ge=1, le=100)
    tone: Tone = Tone.FRIENDLY
    custom_tone_prompt: str | None = None
    vk_account_id: int | None = None
    timezone: str = "Europe/Moscow"
    posting_times: list[str] = Field(default_factory=lambda: ["10:00", "19:00"])
    autopilot: bool = False
    auto_approve: bool = False
    images_enabled: bool = True
    image_format: ImageFormat = ImageFormat.SQUARE
    auto_reply_mode: AutoReplyMode = AutoReplyMode.APPROVAL
    auto_reply_types: list[InboxClass] = Field(default_factory=lambda: [InboxClass.QUESTION])

    @field_validator("posting_times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        for item in value:
            parts = item.split(":")
            if len(parts) != 2 or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
                raise ValueError(f"invalid time {item!r}, expected HH:MM")
        return [f"{int(t.split(':')[0]):02d}:{int(t.split(':')[1]):02d}" for t in value]

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        from zoneinfo import ZoneInfo

        ZoneInfo(value)
        return value


class ProjectCreate(ProjectBase):
    pass


class ProjectUpdate(BaseModel):
    name: str | None = None
    business_name: str | None = None
    theme: str | None = None
    niche: str | None = None
    city: str | None = None
    target_audience: str | None = None
    product_description: str | None = None
    advantages: str | None = None
    website: str | None = None
    contacts: str | None = None
    goal: ProjectGoal | None = None
    posts_per_day: int | None = Field(default=None, ge=1, le=20)
    posts_per_week: int | None = Field(default=None, ge=1, le=100)
    tone: Tone | None = None
    custom_tone_prompt: str | None = None
    vk_account_id: int | None = None
    timezone: str | None = None
    posting_times: list[str] | None = None
    autopilot: bool | None = None
    auto_approve: bool | None = None
    images_enabled: bool | None = None
    image_format: ImageFormat | None = None
    auto_reply_mode: AutoReplyMode | None = None
    auto_reply_types: list[InboxClass] | None = None
    status: str | None = None
    network: str | None = Field(default=None, max_length=255)

    @field_validator("posting_times")
    @classmethod
    def _times(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else ProjectBase._times(value)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return None if value is None else ProjectBase._tz(value)


class RubricOut(ORMModel):
    id: int
    code: str
    name: str
    description: str | None
    weight: float
    is_active: bool


class RubricUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    weight: float | None = Field(default=None, ge=0, le=10)
    is_active: bool | None = None


class RubricCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str
    description: str | None = None
    weight: float = 1.0


class ProjectOut(ORMModel):
    id: int
    name: str
    business_name: str
    theme: str | None
    niche: str | None
    city: str | None
    target_audience: str | None
    product_description: str | None
    advantages: str | None
    website: str | None
    contacts: str | None
    goal: str
    posts_per_day: int | None
    posts_per_week: int | None
    tone: str
    custom_tone_prompt: str | None
    vk_account_id: int | None
    status: str
    network: str | None = None
    timezone: str
    posting_times: list[str]
    autopilot: bool
    auto_approve: bool
    images_enabled: bool
    image_format: str
    auto_reply_mode: str
    auto_reply_types: list[str]
    context_summary: str | None
    brand: dict[str, Any]
    content_rules: dict[str, Any]
    community_id: int | None = None
    community_name: str | None = None
    created_at: datetime

    @classmethod
    def from_model(cls, project) -> ProjectOut:  # noqa: ANN001
        out = cls.model_validate(project)
        if project.community is not None:
            out.community_id = project.community.id
            out.community_name = project.community.name
        return out


class ProjectDetail(ProjectOut):
    setup_proposal: dict[str, Any]
    rubrics: list[RubricOut] = []
    strategy: dict[str, Any] | None = None
    strategy_version: int | None = None


class SetupRequest(BaseModel):
    force: bool = False


class CommunityPreview(BaseModel):
    name_options: list[str]
    description: str
    status: str
    design: dict[str, Any]
    rubrics: list[dict[str, Any]]
    strategy: dict[str, Any]
    pinned_post: dict[str, Any]
    analysis: dict[str, Any]


class CommunityCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=48)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, max_length=139)
    public_category: int | None = None
    subtype: int | None = None
    pinned_post: dict[str, str] | None = None
    first_queue: bool = True
    queue_size: int = Field(default=3, ge=0, le=20)
    force: bool = False


class CommunityConnectRequest(BaseModel):
    vk_group_id: int
    community_token: str | None = None
    apply_settings: bool = False
    description: str | None = None
    status: str | None = Field(default=None, max_length=139)
    pinned_post: dict[str, str] | None = None
    first_queue: bool = False
    queue_size: int = Field(default=3, ge=0, le=20)
    force: bool = False


class EventsSetupRequest(BaseModel):
    mode: EventMode


class ContentPlanRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=31)
    count: int | None = Field(default=None, ge=1, le=60)
    force: bool = False


class PlanItemOut(ORMModel):
    id: int
    project_id: int
    rubric_code: str
    topic: str
    angle: str | None
    planned_for: datetime | None
    status: str
    post_id: int | None


class PlanItemUpdate(BaseModel):
    topic: str | None = None
    angle: str | None = None
    rubric_code: str | None = None
    status: str | None = None
