from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse


def _configure(client, headers):  # noqa: ANN001
    r = client.put("/api/vk/oauth/config", json={"app_id": 54805330, "secret": "app-secret", "flow": "classic"}, headers=headers)
    assert r.status_code == 200 and r.json()["configured"] is True
    assert r.json()["redirect_uri"] == "https://panel.example.com/api/vk/oauth/callback"


def _start(client, headers, **body):  # noqa: ANN001
    url = client.post("/api/vk/oauth/start", json=body, headers=headers).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert q["response_type"] == ["code"] and q["client_id"] == ["54805330"]
    assert "offline" not in q["scope"][0]
    return q["state"][0]


def test_server_side_login_creates_account(client, admin_headers, vk):
    _configure(client, admin_headers)
    state = _start(client, admin_headers, name="Основной")
    r = client.get("/api/vk/oauth/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    assert r.status_code == 302 and "vk_ok=" in r.headers["location"]
    assert "24" in unquote(r.headers["location"])
    accounts = client.get("/api/accounts", headers=admin_headers).json()
    assert accounts[0]["name"] == "Основной" and accounts[0]["status"] == "active"
    assert accounts[0]["info"]["auth"] == "server_oauth" and accounts[0]["info"]["token_expires_at"]
    assert vk.oauth_requests[0]["redirect_uri"] == "https://panel.example.com/api/vk/oauth/callback"


def test_relogin_updates_existing_account(client, admin_headers, vk):
    _configure(client, admin_headers)
    acc = client.post("/api/accounts", json={"name": "Old", "access_token": "vk1.a.expired-token"}, headers=admin_headers).json()
    assert acc["status"] == "invalid"
    state = _start(client, admin_headers, account_id=acc["id"])
    client.get("/api/vk/oauth/callback", params={"code": "good-code", "state": state}, follow_redirects=False)
    acc = client.get(f"/api/accounts/{acc['id']}", headers=admin_headers).json()
    assert acc["status"] == "active"
    assert len(client.get("/api/accounts", headers=admin_headers).json()) == 1


def test_bad_code_and_bad_state(client, admin_headers, vk):
    _configure(client, admin_headers)
    state = _start(client, admin_headers, name="X")
    r = client.get("/api/vk/oauth/callback", params={"code": "bad", "state": state}, follow_redirects=False)
    assert "vk_error=" in r.headers["location"] and "invalid" in unquote(r.headers["location"]).lower()
    r = client.get("/api/vk/oauth/callback", params={"code": "good-code", "state": "forged"}, follow_redirects=False)
    assert "vk_error=" in r.headers["location"]
    r = client.get("/api/vk/oauth/callback", params={"error": "access_denied", "error_description": "User denied"},
                   follow_redirects=False)
    assert "User denied" in unquote(r.headers["location"])
    assert client.get("/api/accounts", headers=admin_headers).json() == []


def test_secret_never_returned(client, admin_headers, viewer_headers, vk):
    _configure(client, admin_headers)
    assert "app-secret" not in client.get("/api/vk/oauth/config", headers=admin_headers).text
    assert client.put("/api/vk/oauth/config", json={"app_id": 1, "secret": "x"}, headers=viewer_headers).status_code == 403


def test_vkid_flow_with_pkce_and_auto_refresh(client, admin_headers, vk, db):
    from datetime import timedelta

    from app.db.base import utcnow
    from app.models.vk_account import VKAccount
    from app.workers.tasks.maintenance import refresh_vk_tokens

    r = client.put("/api/vk/oauth/config", json={"app_id": 777, "flow": "vkid"}, headers=admin_headers)
    assert r.json()["configured"] is True and r.json()["flow"] == "vkid"
    url = client.post("/api/vk/oauth/start", json={"name": "VKID"}, headers=admin_headers).json()["url"]
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://id.vk.com/authorize") and q["code_challenge_method"] == ["S256"]
    state = q["state"][0]
    r = client.get("/api/vk/oauth/callback", params={"code": "good-code", "state": state, "device_id": "dev-1"},
                   follow_redirects=False)
    assert "vk_ok=" in r.headers["location"], unquote(r.headers["location"])
    assert vk.oauth_requests[-1]["code_verifier"] and vk.oauth_requests[-1]["device_id"] == "dev-1"
    # state is one-time
    r = client.get("/api/vk/oauth/callback", params={"code": "good-code", "state": state, "device_id": "dev-1"},
                   follow_redirects=False)
    assert "vk_error=" in r.headers["location"]

    account = db.query(VKAccount).one()
    assert account.refresh_token == "rt-1" and account.device_id == "dev-1"
    account.token_expires_at = utcnow() + timedelta(minutes=5)
    db.commit()
    assert refresh_vk_tokens() == {"due": 1, "refreshed": 1}
    db.expire_all()
    account = db.query(VKAccount).one()
    assert account.refresh_token == "rt-2" and account.token_expires_at > utcnow() + timedelta(minutes=50)
