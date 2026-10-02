from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.proxy import Proxy
from app.models.user import User
from app.models.vk_account import VKAccount
from app.proxy.pool import bind_proxy, check_proxy, import_proxies
from app.schemas.proxy import ProxyImport, ProxyImportResult, ProxyOut, ProxyUpdate
from app.services.audit import audit

router = APIRouter(prefix="/proxies", tags=["proxies"])


def _get(db: Session, proxy_id: int) -> Proxy:
    proxy = db.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "Proxy not found")
    return proxy


@router.get("", response_model=list[ProxyOut])
def list_proxies(status: str | None = None, free: bool | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require(Permission.VIEW))) -> list[ProxyOut]:
    query = select(Proxy).order_by(Proxy.id)
    if status:
        query = query.where(Proxy.status == status)
    bound = select(VKAccount.proxy_id).where(VKAccount.proxy_id.is_not(None))
    if free is True:
        query = query.where(Proxy.id.not_in(bound))
    elif free is False:
        query = query.where(Proxy.id.in_(bound))
    return [ProxyOut.from_model(p) for p in db.execute(query).scalars()]


@router.post("/import", response_model=ProxyImportResult)
def import_list(body: ProxyImport, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.MANAGE_PROXIES))) -> ProxyImportResult:
    result = import_proxies(db, body.text, body.default_scheme)
    audit(db, user.id, "proxy.import", "proxy", None,
          {"created": len(result["created"]), "errors": len(result["errors"])}, client_ip(request))
    db.commit()
    check_job = None
    if body.check and result["created"]:
        from app.workers.tasks.maintenance import check_proxies

        check_job = str(check_proxies.delay(result["created"]).id)
    return ProxyImportResult(**result, check_job=check_job)


@router.post("/check-all")
def check_all(_: User = Depends(require(Permission.MANAGE_PROXIES))) -> dict:
    from app.workers.tasks.maintenance import check_all_proxies

    return {"task_id": str(check_all_proxies.delay().id)}


@router.post("/{proxy_id}/check", response_model=ProxyOut)
def check_one(proxy_id: int, db: Session = Depends(get_db),
              _: User = Depends(require(Permission.MANAGE_PROXIES))) -> ProxyOut:
    proxy = check_proxy(db, _get(db, proxy_id))
    db.commit()
    return ProxyOut.from_model(proxy)


@router.patch("/{proxy_id}", response_model=ProxyOut)
def update_proxy(proxy_id: int, body: ProxyUpdate, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_PROXIES))) -> ProxyOut:
    proxy = _get(db, proxy_id)
    changes = body.model_dump(exclude_unset=True)
    if "scheme" in changes and changes["scheme"]:
        changes["scheme"] = changes["scheme"].value
    for key, value in changes.items():
        setattr(proxy, key, value)
    audit(db, user.id, "proxy.update", "proxy", proxy.id, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return ProxyOut.from_model(proxy)


@router.post("/{proxy_id}/assign", response_model=ProxyOut)
def assign(proxy_id: int, account_id: int, request: Request, db: Session = Depends(get_db),
           user: User = Depends(require(Permission.MANAGE_PROXIES))) -> ProxyOut:
    proxy = _get(db, proxy_id)
    account = db.get(VKAccount, account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    try:
        bind_proxy(db, account, proxy)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, user.id, "proxy.assign", "proxy", proxy.id, {"account_id": account.id}, client_ip(request))
    db.commit()
    db.refresh(proxy)
    return ProxyOut.from_model(proxy)


@router.delete("/{proxy_id}", status_code=204)
def delete_proxy(proxy_id: int, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_PROXIES))) -> None:
    proxy = _get(db, proxy_id)
    audit(db, user.id, "proxy.delete", "proxy", proxy.id, {"host": proxy.host}, client_ip(request))
    db.delete(proxy)
    db.commit()
