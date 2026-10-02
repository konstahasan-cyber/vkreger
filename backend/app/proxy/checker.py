"""Connectivity check for a proxy: external IP, country and latency."""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.core.config import settings


@dataclass
class ProxyCheckResult:
    alive: bool
    external_ip: str | None = None
    country: str | None = None
    country_code: str | None = None
    latency_ms: int | None = None
    error: str | None = None


def check_proxy_url(proxy_url: str | None, *, transport: httpx.BaseTransport | None = None) -> ProxyCheckResult:
    """Fetch ``PROXY_CHECK_URL`` through the proxy.

    The default endpoint (ip-api.com) returns JSON with ``query`` (IP) and country fields;
    any endpoint returning ``{"ip": ...}`` (e.g. api.ipify.org?format=json) also works.
    """
    started = time.perf_counter()
    try:
        with httpx.Client(
            proxy=proxy_url if transport is None else None,
            transport=transport,
            timeout=settings.PROXY_CHECK_TIMEOUT,
            follow_redirects=True,
        ) as client:
            response = client.get(settings.PROXY_CHECK_URL)
        latency = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            return ProxyCheckResult(alive=False, latency_ms=latency, error=f"HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            return ProxyCheckResult(alive=True, latency_ms=latency, external_ip=response.text.strip()[:64] or None)
        if data.get("status") == "fail":
            # ip-api answers "fail" for reserved ranges — the proxy itself works
            return ProxyCheckResult(alive=True, latency_ms=latency, external_ip=data.get("query"))
        return ProxyCheckResult(
            alive=True,
            latency_ms=latency,
            external_ip=data.get("query") or data.get("ip"),
            country=data.get("country"),
            country_code=data.get("countryCode") or data.get("country_code"),
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        # str(exc) can include the proxy URL; never return credentials
        from app.core.logging import redact

        return ProxyCheckResult(alive=False, error=redact(f"{type(exc).__name__}: {exc}")[:500])
