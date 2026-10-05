from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse


def _configure(client, headers):  # noqa: ANN001
    r = client.put("/api/vk/oauth/config", json={"app_id": 54805330, "secret": "app-secret"}, headers=headers)
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
