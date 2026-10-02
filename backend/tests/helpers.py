from __future__ import annotations

from tests.vk_mock import VALID_USER_TOKEN


def add_account(client, headers, **extra) -> dict:  # noqa: ANN001
    body = {"name": "Main", "access_token": VALID_USER_TOKEN, **extra}
    response = client.post("/api/accounts", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_project(client, headers, account_id: int | None = None, **extra) -> dict:  # noqa: ANN001
    body = {
        "name": "Coffee Project", "business_name": "Кофейня Зерно", "theme": "кофе", "niche": "кофейни",
        "city": "Казань", "target_audience": "студенты и офисные сотрудники", "product_description": "specialty кофе",
        "advantages": "своя обжарка", "website": "https://zerno.example", "contacts": "+7 900 000-00-00",
        "goal": "leads", "posts_per_week": 7, "tone": "friendly", "vk_account_id": account_id, **extra,
    }
    response = client.post("/api/projects", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def setup_project_with_community(client, headers, vk, **project_extra) -> dict:  # noqa: ANN001
    account = add_account(client, headers)
    project = create_project(client, headers, account["id"], **project_extra)
    job = client.post(f"/api/projects/{project['id']}/setup", json={}, headers=headers).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).json()["status"] == "success"
    response = client.post(f"/api/projects/{project['id']}/community/connect",
                           json={"vk_group_id": 101, "community_token": "vk1.a.community-token"}, headers=headers)
    assert response.status_code == 200, response.text
    return client.get(f"/api/projects/{project['id']}", headers=headers).json()
