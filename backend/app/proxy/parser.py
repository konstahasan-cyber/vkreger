"""Parsing of proxy lines in the formats users typically get from providers.

Supported (scheme defaults to ``http`` when omitted)::

    IP:PORT
    IP:PORT:LOGIN
    IP:PORT:LOGIN:PASSWORD
    LOGIN@IP
    LOGIN@IP:PORT
    LOGIN:PASSWORD@IP:PORT
    http://LOGIN:PASSWORD@IP:PORT
    https://IP:PORT
    socks5://LOGIN@IP
    socks5h://LOGIN:PASSWORD@IP:PORT
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import unquote

from app.core.config import settings
from app.models.enums import ProxyScheme

_SCHEMES = {
    "http": ProxyScheme.HTTP,
    "https": ProxyScheme.HTTPS,
    "socks5": ProxyScheme.SOCKS5,
    "socks5h": ProxyScheme.SOCKS5,
    "socks": ProxyScheme.SOCKS5,
}
_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+$")


class ProxyParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedProxy:
    scheme: ProxyScheme
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    def key(self) -> tuple[str, str, int, str | None]:
        return (self.scheme.value, self.host, self.port, self.username)


def _default_port(scheme: ProxyScheme) -> int:
    return settings.PROXY_DEFAULT_SOCKS_PORT if scheme == ProxyScheme.SOCKS5 else settings.PROXY_DEFAULT_HTTP_PORT


def _validate_host(host: str) -> str:
    host = host.strip().strip("[]")
    if not host:
        raise ProxyParseError("empty host")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if not _HOST_RE.match(host) or "." not in host:
        raise ProxyParseError(f"invalid host: {host!r}")
    return host.lower()


def _parse_port(value: str) -> int:
    if not value.isdigit():
        raise ProxyParseError(f"invalid port: {value!r}")
    port = int(value)
    if not 0 < port < 65536:
        raise ProxyParseError(f"port out of range: {port}")
    return port


def _split_host_port(value: str, scheme: ProxyScheme) -> tuple[str, int]:
    if value.count(":") == 1:
        host, port = value.split(":")
        return _validate_host(host), _parse_port(port)
    if ":" not in value:
        return _validate_host(value), _default_port(scheme)
    raise ProxyParseError(f"invalid host:port: {value!r}")


def parse_proxy(line: str, default_scheme: ProxyScheme = ProxyScheme.HTTP) -> ParsedProxy:
    raw = line.strip()
    if not raw:
        raise ProxyParseError("empty line")
    scheme = default_scheme
    if "://" in raw:
        prefix, raw = raw.split("://", 1)
        try:
            scheme = _SCHEMES[prefix.lower()]
        except KeyError as exc:
            raise ProxyParseError(f"unsupported scheme: {prefix}") from exc
    raw = raw.rstrip("/")

    username: str | None = None
    password: str | None = None
    if "@" in raw:
        creds, hostpart = raw.rsplit("@", 1)
        if ":" in creds:
            username, password = creds.split(":", 1)
        else:
            username = creds
        host, port = _split_host_port(hostpart, scheme)
    else:
        parts = raw.split(":")
        if len(parts) == 1:
            host, port = _validate_host(parts[0]), _default_port(scheme)
        elif len(parts) == 2:
            host, port = _validate_host(parts[0]), _parse_port(parts[1])
        elif len(parts) == 3:
            host, port, username = _validate_host(parts[0]), _parse_port(parts[1]), parts[2]
        elif len(parts) >= 4:
            host, port, username = _validate_host(parts[0]), _parse_port(parts[1]), parts[2]
            password = ":".join(parts[3:])
        else:  # pragma: no cover
            raise ProxyParseError("cannot parse")

    username = unquote(username) if username else None
    password = unquote(password) if password else None
    return ParsedProxy(scheme=scheme, host=host, port=port, username=username, password=password)


@dataclass
class BulkParseResult:
    proxies: list[ParsedProxy]
    errors: list[dict]


def parse_proxy_list(text: str, default_scheme: ProxyScheme = ProxyScheme.HTTP) -> BulkParseResult:
    proxies: list[ParsedProxy] = []
    errors: list[dict] = []
    seen: set[tuple] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            parsed = parse_proxy(line, default_scheme)
        except ProxyParseError as exc:
            # don't echo the raw line back: it may contain a password
            errors.append({"line": lineno, "error": str(exc)})
            continue
        if parsed.key() in seen:
            continue
        seen.add(parsed.key())
        proxies.append(parsed)
    return BulkParseResult(proxies=proxies, errors=errors)
