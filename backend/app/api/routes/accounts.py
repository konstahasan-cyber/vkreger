from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.user import User
from app.models.vk_account import VKAccount
from app.schemas.account import AccountCreate, AccountOut, AccountProxyUpdate, AccountUpdate
from app.schemas.community import CommunityOut
from app.services import account_service, community_service
from app.services.audit import audit
from app.vk.errors import VKError, describe_vk_error

router = APIRouter(prefix="/accounts", tags=["vk accounts"])


@router.get("", response_model=list[AccountOut])
def list_accounts(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[AccountOut]:
    return [AccountOut.from_model(a) for a in db.execute(select(VKAccount).order_by(VKAccount.id)).scalars()]


@router.post("", response_model=AccountOut, status_code=201)
def add_account(body: AccountCreate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> AccountOut:
    try:
        account = account_service.create_account(db, name=body.name, access_token=body.access_token,
                                                 proxy_id=body.proxy_id, auto_replace_proxy=body.auto_replace_proxy)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, user.id, "account.create", "vk_account", account.id,
          {"name": account.name, "proxy_id": body.proxy_id}, client_ip(request))
    db.commit()
    return AccountOut.from_model(account)


@router.get("/{account_id}", response_model=AccountOut)
def get_account(account_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> AccountOut:
    return AccountOut.from_model(account_service.get_account(db, account_id))


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: int, body: AccountUpdate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> AccountOut:
    account = account_service.get_account(db, account_id)
    account_service.update_account(db, account, **body.model_dump(exclude_unset=True))
    audit(db, user.id, "account.update", "vk_account", account.id,
          {"fields": sorted(body.model_dump(exclude_unset=True))}, client_ip(request))
    db.commit()
    return AccountOut.from_model(account)


@router.put("/{account_id}/proxy", response_model=AccountOut)
def set_proxy(account_id: int, body: AccountProxyUpdate, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> AccountOut:
    account = account_service.get_account(db, account_id)
    try:
        account_service.set_account_proxy(db, account, body.proxy_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    audit(db, user.id, "account.set_proxy", "vk_account", account.id, {"proxy_id": body.proxy_id}, client_ip(request))
    db.commit()
    return AccountOut.from_model(account)


@router.post("/{account_id}/check", response_model=AccountOut)
def check(account_id: int, db: Session = Depends(get_db),
          _: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> AccountOut:
    account = account_service.check_account(db, account_service.get_account(db, account_id), refresh_groups=False)
    db.commit()
    return AccountOut.from_model(account)


@router.post("/{account_id}/refresh", response_model=AccountOut)
def refresh(account_id: int, db: Session = Depends(get_db),
            _: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> AccountOut:
    account = account_service.get_account(db, account_id)
    account_service.check_account(db, account, refresh_groups=True)
    if account.status == "active":
        try:
            community_service.sync_account_communities(db, account)
        except VKError as exc:
            account.last_error = str(exc)
    db.commit()
    return AccountOut.from_model(account)


@router.get("/{account_id}/communities", response_model=list[CommunityOut])
def account_communities(account_id: int, sync: bool = False, db: Session = Depends(get_db),
                        _: User = Depends(require(Permission.VIEW))) -> list[CommunityOut]:
    account = account_service.get_account(db, account_id)
    if sync:
        try:
            communities = community_service.sync_account_communities(db, account)
        except VKError as exc:
            raise HTTPException(502, describe_vk_error(exc)) from exc
        db.commit()
    else:
        communities = account.communities
    return [CommunityOut.from_model(c) for c in communities]


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_ACCOUNTS))) -> None:
    account = account_service.get_account(db, account_id)
    audit(db, user.id, "account.delete", "vk_account", account.id, {"name": account.name}, client_ip(request))
    db.delete(account)
    db.commit()
