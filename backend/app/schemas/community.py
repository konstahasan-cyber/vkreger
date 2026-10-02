from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.common import ORMModel


class CommunityOut(ORMModel):
    id: int
    vk_group_id: int
    name: str
    screen_name: str | None
    description: str | None
    photo_url: str | None
    members_count: int | None
    is_admin: bool
    created_by_app: bool
    account_id: int | None
    project_id: int | None
    event_mode: str
    has_community_token: bool = False
    callback_server_id: int | None
    pinned_post_id: int | None
    last_synced_at: datetime | None
    last_error: str | None
    settings: dict[str, Any]

    @classmethod
    def from_model(cls, community) -> CommunityOut:  # noqa: ANN001
        out = cls.model_validate(community)
        out.has_community_token = bool(community.community_token)
        return out


class CommunityUpdate(BaseModel):
    community_token: str | None = None
    project_id: int | None = None
    detach_project: bool = False


class CommunitySettingsRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    website: str | None = None
