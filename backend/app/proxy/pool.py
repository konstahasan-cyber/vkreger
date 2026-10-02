"""Proxy pool operations: import, check, bind to accounts, replace dead proxies."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import utcnow
from app.models.enums import LogLevel, ProxyScheme, ProxyStatus
from app.models.proxy import Proxy
from app.models.vk_account import VKAccount
from app.proxy.checker import ProxyCheckResult, check_proxy_url
from app.proxy.parser import parse_proxy_list
from app.services.audit import syslog


def import_proxies(db: Session, text: str, default_scheme: ProxyScheme = ProxyScheme.HTTP) -> dict:
    parsed = parse_proxy_list(text, default_scheme)
    created: list[Proxy] = []
    skipped = 0
    for item in parsed.proxies:
        exists = db.execute(
            select(Proxy.id).where(
                Proxy.scheme == item.scheme.value, Proxy.host == item.host, Proxy.port == item.port,
                Proxy.username.is_(None) if item.username is None else Proxy.username == item.username,
            )
        ).first()
        if exists:
            skipped += 1
            continue
        proxy = Proxy(scheme=item.scheme.value, host=item.host, port=item.port,
                      username=item.username, password=item.password)
        db.add(proxy)
        created.append(proxy)
    db.flush()
    return {"created": [p.id for p in created], "skipped_duplicates": skipped, "errors": parsed.errors}


def apply_check_result(db: Session, proxy: Proxy, result: ProxyCheckResult) -> Proxy:
    proxy.last_checked_at = utcnow()
    proxy.latency_ms = result.latency_ms
    if result.alive:
        proxy.status = ProxyStatus.ALIVE.value
        proxy.fail_count = 0
        proxy.last_error = None
        proxy.external_ip = result.external_ip or proxy.external_ip
        proxy.country = result.country or proxy.country
        proxy.country_code = result.country_code or proxy.country_code
    else:
        proxy.fail_count = (proxy.fail_count or 0) + 1
        proxy.last_error = result.error
        if proxy.fail_count >= settings.PROXY_DEAD_AFTER_FAILS or proxy.status != ProxyStatus.ALIVE.value:
            proxy.status = ProxyStatus.DEAD.value
    return proxy


def check_proxy(db: Session, proxy: Proxy, *, auto_replace: bool = True) -> Proxy:
    result = check_proxy_url(proxy.url())
    apply_check_result(db, proxy, result)
    if proxy.status == ProxyStatus.DEAD.value and auto_replace:
        account = db.execute(select(VKAccount).where(VKAccount.proxy_id == proxy.id)).scalar_one_or_none()
        if account and account.auto_replace_proxy:
            replace_account_proxy(db, account)
    db.flush()
    return proxy


def check_many(db: Session, proxies: list[Proxy], *, workers: int = 16) -> list[Proxy]:
    urls = {p.id: p.url() for p in proxies}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(proxies) or 1))) as pool:
        results = dict(zip(urls, pool.map(check_proxy_url, urls.values()), strict=True))
    for proxy in proxies:
        apply_check_result(db, proxy, results[proxy.id])
    db.flush()
    for proxy in proxies:
        if proxy.status == ProxyStatus.DEAD.value:
            account = db.execute(select(VKAccount).where(VKAccount.proxy_id == proxy.id)).scalar_one_or_none()
            if account and account.auto_replace_proxy:
                replace_account_proxy(db, account)
    db.flush()
    return proxies


def free_alive_proxy(db: Session, prefer_country: str | None = None) -> Proxy | None:
    bound = select(VKAccount.proxy_id).where(VKAccount.proxy_id.is_not(None))
    query = (
        select(Proxy)
        .where(Proxy.status == ProxyStatus.ALIVE.value, Proxy.id.not_in(bound))
        .order_by(Proxy.latency_ms.asc().nulls_last(), Proxy.id)
    )
    candidates = db.execute(query.limit(50)).scalars().all()
    if prefer_country:
        for proxy in candidates:
            if proxy.country_code == prefer_country:
                return proxy
    return candidates[0] if candidates else None


def bind_proxy(db: Session, account: VKAccount, proxy: Proxy | None) -> None:
    if proxy is not None:
        other = db.execute(
            select(VKAccount).where(VKAccount.proxy_id == proxy.id, VKAccount.id != account.id)
        ).scalar_one_or_none()
        if other:
            raise ValueError(f"proxy #{proxy.id} is already bound to account #{other.id}")
    account.proxy_id = proxy.id if proxy else None
    account.proxy = proxy
    db.flush()


def replace_account_proxy(db: Session, account: VKAccount) -> Proxy | None:
    old = account.proxy
    replacement = free_alive_proxy(db, prefer_country=old.country_code if old else None)
    if replacement is None:
        syslog(db, LogLevel.WARNING, "proxy",
               f"Proxy of account #{account.id} is dead and no free alive proxy is available",
               context={"account_id": account.id, "proxy_id": old.id if old else None})
        return None
    account.proxy_id = None
    db.flush()
    bind_proxy(db, account, replacement)
    syslog(db, LogLevel.INFO, "proxy",
           f"Account #{account.id}: dead proxy #{old.id if old else '-'} replaced with #{replacement.id}",
           context={"account_id": account.id, "old_proxy_id": old.id if old else None, "new_proxy_id": replacement.id})
    return replacement
