"""Build VK clients bound to an account's network configuration (proxy)."""
from __future__ import annotations

import httpx

from app.models.enums import ProxyStatus
from app.models.vk_account import VKAccount
from app.vk.client import VKClient
from app.vk.errors import ProxyUnavailableError

# Tests replace this with an httpx.MockTransport.
_transport_override: httpx.BaseTransport | None = None


def set_transport_override(transport: httpx.BaseTransport | None) -> None:
    global _transport_override
    _transport_override = transport


def proxy_url_for_account(account: VKAccount) -> str | None:
    if account.proxy_id is None or account.proxy is None:
        return None  # the account explicitly works without a proxy
    if account.proxy.status == ProxyStatus.DEAD.value:
        raise ProxyUnavailableError(f"proxy #{account.proxy_id} of account #{account.id} is dead")
    return account.proxy.url()


def client_for_account(account: VKAccount) -> VKClient:
    return VKClient(account.access_token, proxy_url=proxy_url_for_account(account), transport=_transport_override)


def client_for_community(community, *, prefer_community_token: bool = True) -> VKClient:  # noqa: ANN001
    """Client for a community: community token when present, else the admin account's token.

    Network always goes through the owning account's proxy.
    """
    account = community.account
    proxy_url = proxy_url_for_account(account) if account else None
    if prefer_community_token and community.community_token:
        return VKClient(community.community_token, proxy_url=proxy_url, transport=_transport_override)
    if account is None:
        raise ProxyUnavailableError(f"community #{community.id} has no account and no community token")
    return VKClient(account.access_token, proxy_url=proxy_url, transport=_transport_override)
