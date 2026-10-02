from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rbac import Role
from app.core.security import hash_password
from app.models.user import User

logger = logging.getLogger(__name__)


def create_user(db: Session, email: str, password: str, role: Role = Role.ADMIN, full_name: str | None = None) -> User:
    user = User(email=email.lower().strip(), password_hash=hash_password(password), role=role.value, full_name=full_name)
    db.add(user)
    db.flush()
    return user


def bootstrap_admin(db: Session) -> User | None:
    """Create the first owner from ADMIN_EMAIL/ADMIN_PASSWORD if there are no users yet."""
    if db.execute(select(func.count()).select_from(User)).scalar_one() > 0:
        return None
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        logger.warning("No users exist and ADMIN_EMAIL/ADMIN_PASSWORD are not set")
        return None
    user = create_user(db, settings.ADMIN_EMAIL, settings.ADMIN_PASSWORD, Role.OWNER, "Owner")
    db.commit()
    logger.info("Bootstrap owner %s created", user.email)
    return user
