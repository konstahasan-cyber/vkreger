"""Server-side VK authorization (Authorization Code Flow).

Tokens obtained in the user's browser (implicit flow) may be bound by VK to the browser's IP,
so they fail when the panel runs on a server in another network. Here the browser only
authorizes; the code is exchanged for the token by the server itself (through the account's
proxy, if any), so the token belongs to the server's network.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.exceptions import ValidationAppError
from app.models.system import AppSetting

SETTING_KEY = "VK_OAUTH_APP"
AUTHORIZE_URL = "https://oauth.vk.com/authorize"
TOKEN_URL = "https://oauth.vk.com/access_token"
SCOPES = ["wall", "groups", "photos", "stats"]


def redirect_uri() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_PREFIX}/vk/oauth/callback"


def get_app(db: Session) -> dict[str, Any] | None:
    row = db.get(AppSetting, SETTING_KEY)
    if not row or not isinstance(row.value, dict) or not row.value.get("app_id"):
        return None
    value = dict(row.value)
    value["secret"] = decrypt(value["secret_enc"]) if value.get("secret_enc") else None
    return value


def save_app(db: Session, app_id: int, secret: str | None, offline: bool) -> None:
    row = db.get(AppSetting, SETTING_KEY)
    current = dict(row.value) if row and isinstance(row.value, dict) else {}
    current["app_id"] = int(app_id)
    current["offline"] = bool(offline)
    if secret:
        current["secret_enc"] = encrypt(secret.strip())
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=current))
    else:
        row.value = current
    db.flush()


def make_state(user_id: int, payload: dict[str, Any]) -> str:
    data = {**payload, "uid": user_id, "purpose": "vk_oauth",
            "exp": datetime.now(UTC) + timedelta(minutes=15)}
    return jwt.encode(data, settings.SECRET_KEY, algorithm="HS256")


def read_state(state: str) -> dict[str, Any]:
    try:
        data = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValidationAppError("Ссылка входа устарела — нажмите «Войти через VK» ещё раз") from exc
    if data.get("purpose") != "vk_oauth":
        raise ValidationAppError("Неверный параметр входа")
    return data


def authorize_url(app: dict[str, Any], state: str) -> str:
    scopes = SCOPES + (["offline"] if app.get("offline") else [])
    return AUTHORIZE_URL + "?" + urlencode({
        "client_id": app["app_id"], "display": "page", "redirect_uri": redirect_uri(), "scope": ",".join(scopes),
        "response_type": "code", "v": settings.VK_API_VERSION, "state": state,
    })


def exchange_code(app: dict[str, Any], code: str, *, proxy_url: str | None,
                  transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    if not app.get("secret"):
        raise ValidationAppError("Не задан «Защищённый ключ» приложения VK")
    params = {"client_id": app["app_id"], "client_secret": app["secret"], "redirect_uri": redirect_uri(), "code": code}
    try:
        with httpx.Client(proxy=proxy_url if transport is None else None, transport=transport, timeout=20) as client:
            data = client.get(TOKEN_URL, params=params).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValidationAppError(f"Не удалось связаться с VK: {type(exc).__name__}") from exc
    if "access_token" not in data:
        raise ValidationAppError(f"VK не выдал токен: {data.get('error_description') or data.get('error') or data}")
    return data
