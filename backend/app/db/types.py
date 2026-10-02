from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

from app.core.crypto import decrypt, encrypt

# JSONB on PostgreSQL, plain JSON elsewhere (tests on SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class EncryptedText(TypeDecorator[str]):
    """Text column transparently encrypted at rest with Fernet.

    The plaintext is only available on the ORM object; the database (and backups)
    only ever see ciphertext.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None or value == "":
            return None
        return encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        return decrypt(value)
