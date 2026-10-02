"""VK Callback API endpoint (https://dev.vk.com/ru/api/callback/getting-started).

VK expects the plain string ``ok`` for every event (or the confirmation code for the
``confirmation`` event).  Events are verified with the per-community secret.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.community import Community
from app.services.inbox_service import ingest_event

router = APIRouter(tags=["vk callback"])
logger = logging.getLogger(__name__)


@router.post("/vk/callback/{community_id}", response_class=PlainTextResponse)
async def callback(community_id: int, request: Request, db: Session = Depends(get_db)) -> str:
    try:
        event = await request.json()
    except ValueError:
        return PlainTextResponse("bad request", status_code=400)
    community = db.get(Community, community_id)
    if community is None or int(event.get("group_id", 0)) != community.vk_group_id:
        return PlainTextResponse("unknown community", status_code=404)
    if event.get("type") == "confirmation":
        return community.confirmation_code or ""
    secret = community.callback_secret
    if secret and not hmac.compare_digest(str(event.get("secret", "")), secret):
        logger.warning("Callback for community %s rejected: bad secret", community_id)
        return PlainTextResponse("forbidden", status_code=403)
    item = ingest_event(db, community, event)
    db.commit()
    if item is not None:
        from app.workers.tasks.inbox import triage

        try:
            triage.delay(item.id)
        except Exception:  # noqa: BLE001 — the periodic triage_pending task will pick it up
            logger.warning("Could not enqueue triage for inbox item %s", item.id)
    return "ok"
