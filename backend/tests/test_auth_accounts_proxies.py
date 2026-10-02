from __future__ import annotations

from app.proxy import pool
from app.proxy.checker import ProxyCheckResult
from tests.helpers import add_account


def test_login_and_rbac(client, admin_headers, viewer_headers):
    assert client.get("/api/auth/me", headers=admin_headers).json()["role"] == "owner"
    assert client.get("/api/dashboard").status_code == 401
    assert client.get("/api/dashboard", headers=viewer_headers).status_code == 200
    r = client.post("/api/proxies/import", json={"text": "1.2.3.4:80", "check": False}, headers=viewer_headers)
    assert r.status_code == 403
    bad = client.post("/api/auth/login", data={"username": "admin@example.com", "password": "nope"})
    assert bad.status_code == 401
    audit = client.get("/api/logs/audit", headers=admin_headers).json()
    assert {"auth.login", "auth.login_failed"} <= {row["action"] for row in audit["items"]}


def test_account_add_check_and_communities(client, admin_headers, vk):
    account = add_account(client, admin_headers)
    assert account["status"] == "active"
    assert account["vk_user_id"] == 1
    assert account["groups_cache"][0]["id"] == 101
    assert "access_token" not in account and "vk1.a" not in str(account)
    communities = client.get(f"/api/accounts/{account['id']}/communities?sync=true", headers=admin_headers).json()
    assert communities[0]["vk_group_id"] == 101
    refreshed = client.post(f"/api/accounts/{account['id']}/check", headers=admin_headers).json()
    assert refreshed["last_checked_at"]


def test_invalid_token_marks_account(client, admin_headers, vk):
    response = client.post("/api/accounts", json={"name": "Bad", "access_token": "vk1.a.revoked-token"},
                           headers=admin_headers)
    account = response.json()
    assert account["status"] == "invalid"
    assert "5" in account["last_error"]
    logs = client.get("/api/logs/system?level=warning", headers=admin_headers).json()
    assert logs["total"] >= 1
    assert "revoked-token" not in str(logs)


def test_proxy_import_check_mask_and_auto_replace(client, admin_headers, vk, monkeypatch):
    text = "1.1.1.1:8080:user:pass1\nsocks5://bob:pw2@2.2.2.2:1080\nhttp://u:p3@3.3.3.3:3128\ngarbage"
    result = client.post("/api/proxies/import", json={"text": text, "check": False}, headers=admin_headers).json()
    assert len(result["created"]) == 3 and len(result["errors"]) == 1
    proxies = client.get("/api/proxies", headers=admin_headers).json()
    assert all("pass1" not in str(p) for p in proxies)
    assert proxies[0]["password_masked"].startswith("pa")

    outcomes = {"1.1.1.1": True, "2.2.2.2": True, "3.3.3.3": True}

    def fake_check(url, **_):
        host = url.split("@")[-1].split(":")[0]
        if outcomes[host]:
            return ProxyCheckResult(alive=True, external_ip=host, country="Germany", country_code="DE", latency_ms=50)
        return ProxyCheckResult(alive=False, error="ConnectTimeout")

    monkeypatch.setattr(pool, "check_proxy_url", fake_check)
    for p in proxies:
        checked = client.post(f"/api/proxies/{p['id']}/check", headers=admin_headers).json()
        assert checked["status"] == "alive" and checked["country"] == "Germany"

    account = add_account(client, admin_headers, proxy_id=proxies[0]["id"])
    assert account["proxy_id"] == proxies[0]["id"]
    # the same proxy cannot be bound to a second account
    conflict = client.post("/api/accounts", json={"name": "Second", "access_token": "vk1.a.user-token-ok",
                                                  "proxy_id": proxies[0]["id"]}, headers=admin_headers)
    assert conflict.status_code == 409

    outcomes["1.1.1.1"] = False
    for _ in range(2):  # dead after PROXY_DEAD_AFTER_FAILS consecutive failures
        client.post(f"/api/proxies/{proxies[0]['id']}/check", headers=admin_headers)
    account = client.get(f"/api/accounts/{account['id']}", headers=admin_headers).json()
    assert account["proxy_id"] in (proxies[1]["id"], proxies[2]["id"])
    dead = client.get("/api/proxies?status=dead", headers=admin_headers).json()
    assert [p["id"] for p in dead] == [proxies[0]["id"]]

    # account can work without a proxy
    detached = client.put(f"/api/accounts/{account['id']}/proxy", json={"proxy_id": None}, headers=admin_headers).json()
    assert detached["proxy_id"] is None


def test_dead_proxy_without_replacement_blocks_requests(client, admin_headers, vk, db):
    from app.models.proxy import Proxy

    proxy = Proxy(scheme="http", host="9.9.9.9", port=80, status="dead")
    db.add(proxy)
    db.commit()
    account = add_account(client, admin_headers, proxy_id=proxy.id)
    assert account["status"] == "error"
    assert "dead" in account["last_error"]
    assert vk.calls == []  # never fell back to a direct connection
