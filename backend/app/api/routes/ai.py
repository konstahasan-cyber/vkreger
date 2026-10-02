from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.config import settings
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.system import AIUsage
from app.models.user import User
from app.openai.usage import CostGuard, usage_report
from app.schemas.logs import AIUsageOut
from app.services.audit import audit
from app.services.settings_service import EDITABLE_KEYS, load_runtime_settings, update_runtime_settings

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    rs = load_runtime_settings(db)
    return {
        "values": rs.as_dict(),
        "editable": sorted(EDITABLE_KEYS),
        "provider": settings.AI_PROVIDER,
        "openai_key_configured": bool(settings.OPENAI_API_KEY),
        "pricing": rs.pricing,
        "image_pricing": rs.image_pricing,
        "operations": ["project_setup", "content_plan", "post_compose", "post_edit", "image_prompt",
                       "analytics_review", "inbox_triage", "embedding", "image_generate"],
    }


@router.put("/settings")
def put_settings(values: dict[str, Any], request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_AI_SETTINGS))) -> dict:
    try:
        rs = update_runtime_settings(db, values)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(db, user.id, "ai.settings_update", "app_settings", None, {"keys": sorted(values)}, client_ip(request))
    db.commit()
    return {"values": rs.as_dict()}


@router.get("/usage")
def usage(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    report = usage_report(db)
    report["limits"] = CostGuard(db, load_runtime_settings(db)).status()
    return report


@router.get("/usage/calls", response_model=list[AIUsageOut])
def usage_calls(project_id: int | None = None, operation: str | None = None, limit: int = 100,
                db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[AIUsage]:
    query = select(AIUsage)
    if project_id:
        query = query.where(AIUsage.project_id == project_id)
    if operation:
        query = query.where(AIUsage.operation == operation)
    return list(db.execute(query.order_by(AIUsage.id.desc()).limit(min(limit, 500))).scalars())


@router.get("/limits")
def limits(project_id: int | None = None, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    return CostGuard(db, load_runtime_settings(db)).status(project_id)
