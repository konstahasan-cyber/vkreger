from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, get_current_user, require
from app.core.rbac import Permission
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.user import User
from app.schemas.auth import TokenOut, UserCreate, UserOut, UserUpdate
from app.services.audit import audit
from app.services.user_service import create_user

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenOut:
    user = db.execute(select(User).where(User.email == form.username.lower().strip())).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        audit(db, None, "auth.login_failed", "user", None, {"email": form.username}, client_ip(request))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    audit(db, user.id, "auth.login", "user", user.id, ip=client_ip(request))
    db.commit()
    return TokenOut(access_token=create_access_token(user.id, {"role": user.role}))


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require(Permission.MANAGE_USERS))) -> list[User]:
    return list(db.execute(select(User).order_by(User.id)).scalars())


@router.post("/users", response_model=UserOut, status_code=201)
def add_user(body: UserCreate, request: Request, db: Session = Depends(get_db),
             current: User = Depends(require(Permission.MANAGE_USERS))) -> User:
    if db.execute(select(User).where(User.email == body.email.lower().strip())).scalar_one_or_none():
        raise HTTPException(409, "Такой пользователь уже есть")
    user = create_user(db, body.email, body.password, body.role, body.full_name)
    audit(db, current.id, "user.create", "user", user.id, {"email": user.email, "role": user.role}, client_ip(request))
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, request: Request, db: Session = Depends(get_db),
                current: User = Depends(require(Permission.MANAGE_USERS))) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    changes = body.model_dump(exclude_unset=True)
    if "password" in changes:
        user.password_hash = hash_password(changes.pop("password"))
    if "role" in changes and changes["role"] is not None:
        changes["role"] = changes["role"].value
    for key, value in changes.items():
        setattr(user, key, value)
    audit(db, current.id, "user.update", "user", user.id, {k: v for k, v in changes.items()}, client_ip(request))
    db.commit()
    return user
