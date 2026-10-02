from __future__ import annotations

from sqlalchemy import select

from app.analytics.collector import collect_recent
from app.db.session import session_scope
from app.models.enums import AccountStatus
from app.models.proxy import Proxy
from app.models.vk_account import VKAccount
from app.proxy.pool import check_many
from app.services.account_service import check_account
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.maintenance.check_all_proxies")
def check_all_proxies() -> dict:
    with session_scope() as db:
        proxies = list(db.execute(select(Proxy)).scalars())
        check_many(db, proxies)
        return {"checked": len(proxies)}


@celery_app.task(name="app.workers.tasks.maintenance.check_proxies")
def check_proxies(proxy_ids: list[int]) -> dict:
    with session_scope() as db:
        proxies = list(db.execute(select(Proxy).where(Proxy.id.in_(proxy_ids))).scalars())
        check_many(db, proxies)
        return {"checked": len(proxies)}


@celery_app.task(name="app.workers.tasks.maintenance.check_all_accounts")
def check_all_accounts() -> dict:
    with session_scope() as db:
        accounts = list(db.execute(select(VKAccount).where(VKAccount.status != AccountStatus.DISABLED.value)).scalars())
        for account in accounts:
            check_account(db, account, refresh_groups=False)
            db.commit()
        return {"checked": len(accounts)}


@celery_app.task(name="app.workers.tasks.maintenance.collect_analytics")
def collect_analytics() -> dict:
    with session_scope() as db:
        return collect_recent(db)
