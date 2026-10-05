from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.exceptions import ValidationAppError
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.community import Community
from app.models.project import Project
from app.models.user import User
from app.schemas.community import CommunityOut, CommunitySettingsRequest, CommunityUpdate
from app.schemas.project import EventsSetupRequest
from app.services import community_service
from app.services.audit import audit
from app.vk.errors import VKAPIError, VKError, describe_vk_error

router = APIRouter(prefix="/communities", tags=["communities"])


@router.get("", response_model=list[CommunityOut])
def list_communities(account_id: int | None = None, connected: bool | None = None, db: Session = Depends(get_db),
                     _: User = Depends(require(Permission.VIEW))) -> list[CommunityOut]:
    query = select(Community).order_by(Community.id)
    if account_id:
        query = query.where(Community.account_id == account_id)
    if connected is True:
        query = query.where(Community.project_id.is_not(None))
    elif connected is False:
        query = query.where(Community.project_id.is_(None))
    return [CommunityOut.from_model(c) for c in db.execute(query).scalars()]


@router.get("/{community_id}", response_model=CommunityOut)
def get_community(community_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> CommunityOut:
    return CommunityOut.from_model(community_service.get_community(db, community_id))


@router.patch("/{community_id}", response_model=CommunityOut)
def update_community(community_id: int, body: CommunityUpdate, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> CommunityOut:
    community = community_service.get_community(db, community_id)
    if body.community_token is not None:
        community.community_token = body.community_token.strip() or None
    if body.detach_project:
        community.project_id = None
    elif body.project_id is not None:
        project = db.get(Project, body.project_id)
        if project is None:
            raise HTTPException(404, "Проект не найден")
        if project.community and project.community.id != community.id:
            raise HTTPException(409, "У проекта уже есть сообщество")
        community.project_id = project.id
    audit(db, user.id, "community.update", "community", community.id,
          {"token_changed": body.community_token is not None, "project_id": body.project_id,
           "detach": body.detach_project}, client_ip(request))
    db.commit()
    return CommunityOut.from_model(community)


@router.post("/{community_id}/settings")
def apply_settings(community_id: int, body: CommunitySettingsRequest, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    community = community_service.get_community(db, community_id)
    try:
        result = community_service.apply_settings(db, community, **body.model_dump())
    except VKError as exc:
        raise HTTPException(502, describe_vk_error(exc)) from exc
    audit(db, user.id, "community.settings", "community", community.id, {"result": result}, client_ip(request))
    db.commit()
    return result


@router.post("/{community_id}/events")
def setup_events(community_id: int, body: EventsSetupRequest, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    community = community_service.get_community(db, community_id)
    try:
        result = community_service.setup_events(db, community, body.mode)
    except VKAPIError as exc:
        db.rollback()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    except (VKError, ValidationAppError) as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    audit(db, user.id, "community.events", "community", community.id, {"mode": body.mode.value}, client_ip(request))
    db.commit()
    return result


@router.post("/{community_id}/sync", response_model=CommunityOut)
def sync(community_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.MANAGE_PROJECTS))) -> CommunityOut:
    from app.vk.factory import run_for_community

    community = community_service.get_community(db, community_id)
    try:
        group = run_for_community(community, lambda c: c.get_group(community.vk_group_id))
    except VKError as exc:
        community.last_error = str(exc)
        db.commit()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    community_service._upsert_from_vk(db, group, community.account)
    community.last_error = None
    db.commit()
    return CommunityOut.from_model(community)
