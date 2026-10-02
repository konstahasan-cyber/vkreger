"""Runtime settings: env defaults overridable from the admin panel (``app_settings``).

Only a whitelisted subset is editable at runtime — infrastructure and secrets stay in env.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.system import AppSetting

EDITABLE_KEYS: dict[str, type | tuple[type, ...]] = {
    "AI_DEFAULT_MODEL": str,
    "AI_MODEL_OVERRIDES": dict,
    "AI_EMBEDDING_MODEL": str,
    "AI_EMBEDDINGS_ENABLED": bool,
    "AI_SEPARATE_EDITOR_PASS": bool,
    "AI_PRICING_JSON": dict,
    "IMAGE_PROVIDER": str,
    "IMAGE_MODEL": str,
    "IMAGE_QUALITY": str,
    "IMAGE_PRICING_JSON": dict,
    "MAX_AI_COST_PER_DAY": (int, float),
    "MAX_AI_COST_PER_PROJECT_DAY": (int, float),
    "SIMILARITY_THRESHOLD": (int, float),
    "TITLE_SIMILARITY_THRESHOLD": (int, float),
    "ANALYST_MIN_INTERVAL_DAYS": int,
    "ANALYST_MIN_NEW_POSTS": int,
    "QUEUE_HORIZON_DAYS": int,
}


class RuntimeSettings:
    """Snapshot of settings with DB overrides applied."""

    def __init__(self, overrides: dict[str, Any]):
        self._overrides = overrides

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        if name in self._overrides:
            return self._overrides[name]
        return getattr(settings, name)

    @property
    def pricing(self) -> dict[str, dict[str, float]]:
        return {**settings.pricing, **(self._overrides.get("AI_PRICING_JSON") or {})}

    @property
    def image_pricing(self) -> dict[str, float]:
        return {**settings.image_pricing, **(self._overrides.get("IMAGE_PRICING_JSON") or {})}

    def model_for(self, operation: str) -> str:
        overrides = {**settings.AI_MODEL_OVERRIDES, **(self._overrides.get("AI_MODEL_OVERRIDES") or {})}
        return overrides.get(operation) or self.AI_DEFAULT_MODEL

    def as_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in EDITABLE_KEYS}


def load_runtime_settings(db: Session) -> RuntimeSettings:
    rows = db.execute(select(AppSetting).where(AppSetting.key.in_(list(EDITABLE_KEYS)))).scalars().all()
    return RuntimeSettings({row.key: row.value for row in rows})


def update_runtime_settings(db: Session, values: dict[str, Any]) -> RuntimeSettings:
    for key, value in values.items():
        if key not in EDITABLE_KEYS:
            raise ValueError(f"setting {key} is not editable")
        expected = EDITABLE_KEYS[key]
        if value is not None and not isinstance(value, expected):
            raise ValueError(f"setting {key} has invalid type")
        row = db.get(AppSetting, key)
        if value is None:
            if row:
                db.delete(row)
            continue
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    db.flush()
    return load_runtime_settings(db)
