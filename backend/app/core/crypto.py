"""Symmetric encryption for secrets stored in the database (VK tokens, proxy passwords).

Uses ``MultiFernet`` so keys can be rotated: put the new key first in
``ENCRYPTION_KEYS`` and keep old keys after it until data is re-encrypted.
"""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import settings


class DecryptionError(Exception):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in settings.ENCRYPTION_KEYS.split(",") if k.strip()]
    if not keys:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError("ENCRYPTION_KEYS must be set in production")
        # Development fallback: derive a key from SECRET_KEY so the app still works.
        digest = hashlib.sha256(("enc:" + settings.SECRET_KEY).encode()).digest()
        keys = [base64.urlsafe_b64encode(digest).decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # pragma: no cover - only with wrong keys
        raise DecryptionError("Cannot decrypt secret: wrong ENCRYPTION_KEYS?") from exc


def mask_secret(value: str | None, visible: int = 2) -> str | None:
    """Return a masked representation, e.g. ``ab******``. Never returns the full value."""
    if not value:
        return None
    if len(value) <= visible * 2:
        return "*" * 8
    return value[:visible] + "*" * 6 + value[-visible:]


def generate_key() -> str:
    return Fernet.generate_key().decode()
