"""Server-side VK authorization.

Tokens obtained in the user's browser (implicit flow) are bound by VK to the browser's IP,
so they fail when the panel runs on a server in another network. Here the browser only
authorizes; the code is exchanged for the token by the server itself (through the account's
proxy, if any).

Two flows are supported:
* ``vkid``    — VK ID (id.vk.com) with PKCE; returns a refresh token, so the panel renews
                access tokens automatically. Recommended; needs an https redirect URL.
* ``classic`` — oauth.vk.com authorization code flow with the app's protected key.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.exceptions import ValidationAppError
from app.models.system import AppSetting

SETTING_KEY = "VK_OAUTH_APP"
STATE_PREFIX = "VK_OAUTH_STATE:"
CLASSIC_AUTHORIZE_URL = "https://oauth.vk.com/authorize"
CLASSIC_TOKEN_URL = "https://oauth.vk.com/access_token"
VKID_AUTHORIZE_URL = "https://id.vk.com/authorize"
VKID_TOKEN_URL = "https://id.vk.com/oauth2/auth"
SCOPES = ["wall", "groups", "photos", "stats"]


def redirect_uri() -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_PREFIX}/vk/oauth/callback"


def get_app(db: Session) -> dict[str, Any] | None:
    row = db.get(AppSetting, SETTING_KEY)
    if not row or not isinstance(row.value, dict) or not row.value.get("app_id"):
        return None
    value = dict(row.value)
    value.setdefault("flow", "classic")
    value["secret"] = decrypt(value["secret_enc"]) if value.get("secret_enc") else None
    return value


def is_configured(app: dict[str, Any] | None) -> bool:
    return bool(app and (app.get("flow") == "vkid" or app.get("secret")))


def save_app(db: Session, app_id: int, secret: str | None, offline: bool, flow: str = "classic") -> None:
    row = db.get(AppSetting, SETTING_KEY)
    current = dict(row.value) if row and isinstance(row.value, dict) else {}
    current.update(app_id=int(app_id), offline=bool(offline), flow=flow if flow in ("vkid", "classic") else "classic")
    if secret:
        current["secret_enc"] = encrypt(secret.strip())
    if row is None:
        db.add(AppSetting(key=SETTING_KEY, value=current))
    else:
        row.value = current
    db.flush()


# ------------------------------------------------------------------ state
def make_state(db: Session, user_id: int, payload: dict[str, Any], flow: str) -> tuple[str, str | None]:
    """Returns (state, code_challenge). VK ID keeps the PKCE verifier server-side."""
    if flow != "vkid":
        data = {**payload, "uid": user_id, "purpose": "vk_oauth",
                "exp": datetime.now(UTC) + timedelta(minutes=15)}
        return jwt.encode(data, settings.SECRET_KEY, algorithm="HS256"), None
    now = datetime.now(UTC)
    db.execute(delete(AppSetting).where(AppSetting.key.like(STATE_PREFIX + "%"),
                                        AppSetting.created_at < now - timedelta(hours=1)))
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    db.add(AppSetting(key=STATE_PREFIX + nonce, value={
        "payload": payload, "uid": user_id, "verifier_enc": encrypt(verifier),
        "exp": (now + timedelta(minutes=15)).isoformat()}))
    db.flush()
    return nonce, challenge


def read_state(db: Session, state: str) -> tuple[dict[str, Any], str | None]:
    """Returns (data with uid + payload fields, pkce verifier or None)."""
    row = db.get(AppSetting, STATE_PREFIX + state) if len(state) < 64 else None
    if row is not None:
        value = row.value or {}
        db.delete(row)  # one-time use
        if datetime.fromisoformat(value["exp"]) < datetime.now(UTC):
            raise ValidationAppError("Ссылка входа устарела — нажмите «Войти через VK» ещё раз")
        return {**value["payload"], "uid": value["uid"]}, decrypt(value["verifier_enc"])
    try:
        data = jwt.decode(state, settings.SECRET_KEY, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ValidationAppError("Ссылка входа устарела — нажмите «Войти через VK» ещё раз") from exc
    if data.get("purpose") != "vk_oauth":
        raise ValidationAppError("Неверный параметр входа")
    return data, None


# ------------------------------------------------------------------ flows
def authorize_url(app: dict[str, Any], state: str, code_challenge: str | None) -> str:
    if app.get("flow") == "vkid":
        return VKID_AUTHORIZE_URL + "?" + urlencode({
            "response_type": "code", "client_id": app["app_id"], "redirect_uri": redirect_uri(), "state": state,
            "code_challenge": code_challenge, "code_challenge_method": "S256", "scope": " ".join(SCOPES),
        })
    scopes = SCOPES + (["offline"] if app.get("offline") else [])
    return CLASSIC_AUTHORIZE_URL + "?" + urlencode({
        "client_id": app["app_id"], "display": "page", "redirect_uri": redirect_uri(), "scope": ",".join(scopes),
        "response_type": "code", "v": settings.VK_API_VERSION, "state": state,
    })


def _client(proxy_url: str | None, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(proxy=proxy_url if transport is None else None, transport=transport, timeout=20)


def _result(data: dict[str, Any]) -> dict[str, Any]:
    if "access_token" not in data:
        raise ValidationAppError(f"VK не выдал токен: {data.get('error_description') or data.get('error') or data}")
    return data


def exchange_code(app: dict[str, Any], code: str, *, proxy_url: str | None, verifier: str | None = None,
                  device_id: str | None = None, state: str | None = None,
                  transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    try:
        with _client(proxy_url, transport) as client:
            if app.get("flow") == "vkid":
                if not verifier or not device_id:
                    raise ValidationAppError("VK ID не вернул device_id — попробуйте войти ещё раз")
                data = client.post(VKID_TOKEN_URL, data={
                    "grant_type": "authorization_code", "code": code, "code_verifier": verifier,
                    "client_id": app["app_id"], "device_id": device_id, "redirect_uri": redirect_uri(),
                    "state": state or secrets.token_urlsafe(16),
                }).json()
            else:
                if not app.get("secret"):
                    raise ValidationAppError("Не задан «Защищённый ключ» приложения VK")
                data = client.get(CLASSIC_TOKEN_URL, params={
                    "client_id": app["app_id"], "client_secret": app["secret"], "redirect_uri": redirect_uri(),
                    "code": code}).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValidationAppError(f"Не удалось связаться с VK: {type(exc).__name__}") from exc
    return _result(data)


def refresh_token(app: dict[str, Any], refresh: str, device_id: str, *, proxy_url: str | None,
                  transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    try:
        with _client(proxy_url, transport) as client:
            data = client.post(VKID_TOKEN_URL, data={
                "grant_type": "refresh_token", "refresh_token": refresh, "client_id": app["app_id"],
                "device_id": device_id, "state": secrets.token_urlsafe(16),
            }).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValidationAppError(f"Не удалось связаться с VK: {type(exc).__name__}") from exc
    return _result(data)
