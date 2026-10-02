from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.models.enums import LogLevel
from app.models.system import AuditLog, SystemLog

logger = logging.getLogger("app.syslog")

_SECRET_KEYS = {"access_token", "token", "password", "community_token", "secret", "api_key", "callback_secret"}


def _scrub(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    clean: dict[str, Any] = {}
    for key, value in details.items():
        if key.lower() in _SECRET_KEYS:
            clean[key] = "***"
        elif isinstance(value, dict):
            clean[key] = _scrub(value)
        elif isinstance(value, str):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


def audit(db: Session, user_id: int | None, action: str, entity_type: str | None = None,
          entity_id: Any = None, details: dict[str, Any] | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(user_id=user_id, action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    details=_scrub(details), ip=ip))


def syslog(db: Session, level: LogLevel | str, source: str, message: str, *,
           project_id: int | None = None, context: dict[str, Any] | None = None) -> None:
    level = LogLevel(level)
    message = redact(message)[:4000]
    getattr(logger, "error" if level == LogLevel.ERROR else level.value)("[%s] %s", source, message)
    db.add(SystemLog(level=level.value, source=source, message=message, project_id=project_id,
                     context=_scrub(context)))
