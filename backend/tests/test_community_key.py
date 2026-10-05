"""Working with a community access key only (no VK user account) and fallback to the account."""
from __future__ import annotations

from tests.helpers import create_project, setup_project_with_community
from tests.vk_mock import COMMUNITY_TOKEN, VALID_USER_TOKEN


def test_project_without_account_works_with_community_key(client, admin_headers, vk):
    project = create_project(client, admin_headers, None)
    job = client.post(f"/api/projects/{project['id']}/setup", json={}, headers=admin_headers).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()["status"] == "success"

    no_key = client.post(f"/api/projects/{project['id']}/community/connect", json={"vk_group_id": 101},
                         headers=admin_headers)
    assert no_key.status_code == 422 and "ключ" in no_key.json()["detail"]

    r = client.post(f"/api/projects/{project['id']}/community/connect", json={
        "vk_group_id": 101, "community_token": COMMUNITY_TOKEN, "apply_settings": True, "description": "Описание",
        "status": "Статус", "pinned_post": {"title": "Привет", "text": "Закреп"}, "first_queue": True, "queue_size": 1,
    }, headers=admin_headers)
    assert r.status_code == 200, r.text
    job = client.get(f"/api/jobs/{r.json()['job']['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    assert job["result"]["settings"] == {"groups.edit": "ok", "status.set": "ok"}
    assert job["result"]["pinned_post"]["status"] == "published"
    assert vk.pinned[-101] == job["result"]["pinned_post"]["vk_post_id"]
    assert {t for m, t in vk.tokens_used if m in ("wall.post", "groups.edit", "wall.pin")} == {COMMUNITY_TOKEN}

    wrong = client.post(f"/api/projects/{project['id']}/community/connect",
                        json={"vk_group_id": 999, "community_token": COMMUNITY_TOKEN}, headers=admin_headers)
    assert wrong.status_code in (409, 422, 502)


def test_falls_back_to_account_when_key_is_refused(client, admin_headers, vk):
    vk.community_forbidden = {"status.set"}
    project = setup_project_with_community(client, admin_headers, vk)
    r = client.post(f"/api/communities/{project['community_id']}/settings", json={"status": "Новый статус"},
                    headers=admin_headers)
    assert r.json() == {"status.set": "ok"}
    used = [t for m, t in vk.tokens_used if m == "status.set"]
    assert used == [COMMUNITY_TOKEN, VALID_USER_TOKEN]
