from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
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
        "openai_key_configured": bool(rs.OPENAI_API_KEY),
        "openai_key_source": "panel" if rs._overrides.get("OPENAI_API_KEY") else ("env" if settings.OPENAI_API_KEY else None),
        "openai_key_hint": f"…{rs.OPENAI_API_KEY[-4:]}" if rs.OPENAI_API_KEY else None,
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


class OpenAIKeyIn(BaseModel):
    key: str | None = Field(default=None, max_length=500)


@router.put("/openai-key")
def put_openai_key(body: OpenAIKeyIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_AI_SETTINGS))) -> dict:
    from app.openai.provider import verify_openai_key
    from app.services.settings_service import save_openai_key

    key = "".join((body.key or "").split())  # drop spaces/line breaks that sneak in when copying
    if key:
        if not key.startswith("sk-"):
            raise HTTPException(422, "Ключ OpenAI должен начинаться с sk-")
        if settings.AI_PROVIDER != "fake":
            error = verify_openai_key(key)
            if error:
                raise HTTPException(422, error)
    save_openai_key(db, key or None)
    audit(db, user.id, "ai.openai_key", "app_settings", None, {"set": bool(key)}, client_ip(request))
    db.commit()
    return {"ok": True, "configured": bool(key) or bool(settings.OPENAI_API_KEY)}
