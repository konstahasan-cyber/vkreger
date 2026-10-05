"""VK account management: import, health checks, communities discovery."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.base import utcnow
from app.models.enums import AccountStatus, LogLevel
from app.models.proxy import Proxy
from app.models.vk_account import VKAccount
from app.proxy.pool import bind_proxy, replace_account_proxy
from app.services.audit import syslog
from app.vk.errors import ProxyUnavailableError, VKAPIError, VKError, describe_vk_error
from app.vk.factory import client_for_account


def get_account(db: Session, account_id: int) -> VKAccount:
    account = db.get(VKAccount, account_id)
    if account is None:
        raise NotFoundError(f"Аккаунт VK #{account_id} не найден")
    return account


def create_account(db: Session, *, name: str, access_token: str, proxy_id: int | None = None,
                   auto_replace_proxy: bool = True, verify: bool = True) -> VKAccount:
    account = VKAccount(name=name, access_token=access_token.strip(), auto_replace_proxy=auto_replace_proxy,
                        status=AccountStatus.NEW.value, info={}, groups_cache=[])
    db.add(account)
    db.flush()
    if proxy_id is not None:
        proxy = db.get(Proxy, proxy_id)
        if proxy is None:
            raise NotFoundError(f"Прокси #{proxy_id} не найден")
        bind_proxy(db, account, proxy)
    if verify:
        check_account(db, account)
    return account


def check_account(db: Session, account: VKAccount, *, refresh_groups: bool = True) -> VKAccount:
    """Verify the token via users.get and refresh cached data. Never raises for VK errors."""
    account.last_checked_at = utcnow()
    try:
        try:
            client = client_for_account(account)
        except ProxyUnavailableError:
            if account.auto_replace_proxy and replace_account_proxy(db, account):
                client = client_for_account(account)
            else:
                raise
        with client:
            user = client.get_current_user()
            account.vk_user_id = int(user["id"])
            permissions = client.get_app_permissions()
            account.info = {
                **(account.info or {}),
                "first_name": user.get("first_name"),
                "last_name": user.get("last_name"),
                "screen_name": user.get("screen_name"),
                "photo": user.get("photo_100"),
                "app_permissions": permissions,
            }
            if refresh_groups:
                account.groups_cache = [
                    {
                        "id": g["id"],
                        "name": g.get("name"),
                        "screen_name": g.get("screen_name"),
                        "members_count": g.get("members_count"),
                        "photo": g.get("photo_100"),
                    }
                    for g in client.get_admin_groups()
                ]
        account.status = AccountStatus.ACTIVE.value
        account.last_error = None
    except VKAPIError as exc:
        account.status = AccountStatus.INVALID.value if exc.is_auth else AccountStatus.ERROR.value
        account.last_error = describe_vk_error(exc)
        syslog(db, LogLevel.WARNING, "vk_account", f"Account #{account.id} check failed: {account.last_error}",
               context={"account_id": account.id})
    except VKError as exc:
        account.status = AccountStatus.ERROR.value
        account.last_error = describe_vk_error(exc)
        syslog(db, LogLevel.WARNING, "vk_account", f"Account #{account.id} check failed: {exc}",
               context={"account_id": account.id})
    db.flush()
    return account


def update_account(db: Session, account: VKAccount, *, name: str | None = None, access_token: str | None = None,
                   auto_replace_proxy: bool | None = None, status: str | None = None) -> VKAccount:
    if name is not None:
        account.name = name
    if auto_replace_proxy is not None:
        account.auto_replace_proxy = auto_replace_proxy
    if status is not None:
        account.status = AccountStatus(status).value
    if access_token:
        account.access_token = access_token.strip()
        check_account(db, account)
    db.flush()
    return account


def set_account_proxy(db: Session, account: VKAccount, proxy_id: int | None) -> VKAccount:
    proxy = None
    if proxy_id is not None:
        proxy = db.get(Proxy, proxy_id)
        if proxy is None:
            raise NotFoundError(f"Прокси #{proxy_id} не найден")
    bind_proxy(db, account, proxy)
    return account


def usable_accounts(db: Session) -> list[VKAccount]:
    from sqlalchemy import select

    return list(db.execute(select(VKAccount).where(VKAccount.status == AccountStatus.ACTIVE.value)).scalars())
