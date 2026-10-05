from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.exceptions import AppError
from app.core.rbac import Permission
from app.db.base import utcnow
from app.db.session import get_db
from app.models.proxy import Proxy
from app.models.user import User
from app.models.vk_account import VKAccount
from app.services import account_service
from app.services.audit import audit
from app.vk import factory, oauth
from app.vk.errors import ProxyUnavailableError

router = APIRouter(prefix="/vk/oauth", tags=["vk oauth"])


class OAuthConfig(BaseModel):
    app_id: int = Field(gt=0)
    secret: str | None = Field(default=None, max_length=200)
    offline: bool = False
    flow: str = Field(default="vkid", pattern="^(vkid|classic)$")


class OAuthStart(BaseModel):
    account_id: int | None = None
    name: str | None = Field(default=None, max_length=255)
    proxy_id: int | None = None


@router.get("/config")
def get_config(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    app = oauth.get_app(db)
    return {"configured": oauth.is_configured(app), "app_id": app["app_id"] if app else None,
            "flow": app.get("flow") if app else "vkid", "has_secret": bool(app and app.get("secret")),
            "offline": bool(app and app.get("offline")), "redirect_uri": oauth.redirect_uri(),
            "https": oauth.redirect_uri().startswith("https://")}


@router.put("/config")
def put_config(body: OAuthConfig, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> dict:
    oauth.save_app(db, body.app_id, body.secret, body.offline, body.flow)
    audit(db, user.id, "vk_oauth.config", "app_settings", None, {"app_id": body.app_id}, client_ip(request))
    db.commit()
    return get_config(db, user)


@router.post("/start")
def start(body: OAuthStart, db: Session = Depends(get_db), user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> dict:
    app = oauth.get_app(db)
    if not oauth.is_configured(app):
        raise HTTPException(409, "Сначала настройте вход через VK (ID приложения)")
    if body.account_id is not None and db.get(VKAccount, body.account_id) is None:
        raise HTTPException(404, "Аккаунт не найден")
    state, challenge = oauth.make_state(db, user.id, body.model_dump(), app["flow"])
    db.commit()
    return {"url": oauth.authorize_url(app, state, challenge)}


def _back(message: str, ok: bool) -> RedirectResponse:
    return RedirectResponse(f"/accounts?{'vk_ok' if ok else 'vk_error'}={quote(message)}", status_code=302)


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             error_description: str | None = None, device_id: str | None = None,
             db: Session = Depends(get_db)) -> RedirectResponse:
    if error:
        return _back(f"VK отказал во входе: {error_description or error}", False)
    if not code or not state:
        return _back("VK не вернул код авторизации", False)
    try:
        data, verifier = oauth.read_state(db, state)
        db.commit()  # the one-time state is consumed even if the exchange fails
        user = db.get(User, int(data["uid"]))
        if user is None or not user.is_active:
            return _back("Пользователь панели не найден", False)
        app = oauth.get_app(db)
        if not app:
            return _back("Вход через VK не настроен", False)
        account = db.get(VKAccount, data["account_id"]) if data.get("account_id") else None
        proxy = account.proxy if account else (db.get(Proxy, data["proxy_id"]) if data.get("proxy_id") else None)
        proxy_url = proxy.url() if proxy else None
        token = oauth.exchange_code(app, code, proxy_url=proxy_url, verifier=verifier, device_id=device_id,
                                    state=state, transport=factory._transport_override)
        expires_in = int(token.get("expires_in") or 0)
        if account is None:
            account = account_service.create_account(db, name=data.get("name") or f"VK {token.get('user_id')}",
                                                     access_token=token["access_token"], proxy_id=data.get("proxy_id"),
                                                     verify=False)
        else:
            account.access_token = token["access_token"]
        account.refresh_token = token.get("refresh_token") or None
        account.device_id = device_id if token.get("refresh_token") else None
        account.token_expires_at = utcnow() + timedelta(seconds=expires_in) if expires_in else None
        account.info = {**(account.info or {}), "auth": "vkid" if account.refresh_token else "server_oauth",
                        "token_expires_at": account.token_expires_at.isoformat() if account.token_expires_at else None}
        account_service.check_account(db, account)
        audit(db, user.id, "vk_oauth.login", "vk_account", account.id, {"vk_user_id": token.get("user_id"),
                                                                         "expires_in": expires_in}, client_ip(request))
        db.commit()
    except (AppError, ProxyUnavailableError, ValueError) as exc:
        db.rollback()
        return _back(getattr(exc, "message", None) or str(exc), False)
    if account.status != "active":
        return _back(f"Токен получен, но не работает: {account.last_error}", False)
    if account.refresh_token:
        hours = " Токен будет продлеваться автоматически."
    else:
        hours = f" Токен действует {expires_in // 3600} ч." if expires_in else " Токен бессрочный."
    return _back(f"Аккаунт «{account.name}» подключён.{hours}", True)
