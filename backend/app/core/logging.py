"""Logging setup with secret redaction.

Access tokens, passwords and API keys must never end up in application logs; the
``RedactingFilter`` scrubs well-known patterns from every record as a safety net.
"""
from __future__ import annotations

import logging
import re
import sys

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(access_token|token|password|secret|api_key|secret_key)(['\"]?\s*[=:]\s*['\"]?)([^\s&'\",}]+)", re.I), r"\1\2***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"vk1\.a\.[A-Za-z0-9_\-]+"), "vk1.a.***"),
    (re.compile(r"sk-[A-Za-z0-9_\-]{10,}"), "sk-***"),
    (re.compile(r"(\w+://[^:/\s]+:)([^@\s]+)(@)"), r"\1***\3"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover
            return True
        record.msg = redact(message)
        record.args = ()
        return True


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # httpx logs full request URLs (which may contain tokens) at INFO level.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
