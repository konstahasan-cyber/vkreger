"""Changing a community's topic: proposals first, then published posts are edited in VK (wall.edit)."""
from __future__ import annotations

from app.models.content import Post
from app.models.project import Project
from tests.helpers import create_project
from tests.vk_mock import COMMUNITY_TOKEN

NEW = {"business_name": "Агентство дизайна Пиксель", "product_description": "логотипы, сайты, фирменный стиль"}


def _project_with_posts(client, headers, vk, published: int = 2, drafts: int = 1) -> dict:  # noqa: ANN001
    project = create_project(client, headers, None, business_name="Рекламное агентство Медиа")
    job = client.post(f"/api/projects/{project['id']}/setup", json={}, headers=headers).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=headers).json()["status"] == "success"
    r = client.post(f"/api/projects/{project['id']}/community/connect",
                    json={"vk_group_id": 101, "community_token": COMMUNITY_TOKEN}, headers=headers)
    assert r.status_code == 200, r.text
    client.patch(f"/api/projects/{project['id']}", json={"status": "active"}, headers=headers)
    ids = []
    for i in range(published + drafts):
        post = client.post("/api/posts", json={"project_id": project["id"], "title": f"Реклама {i}",
                                               "text": f"Как настроить рекламу, совет {i}\n\n#реклама"},
                           headers=headers).json()
        if i < published:
            r = client.post(f"/api/posts/{post['id']}/publish-now", headers=headers)
            assert r.json()["status"] == "published", r.text
        ids.append(post["id"])
    return {"project": project, "posts": ids}


def _run(client, headers, method, path, **kw):  # noqa: ANN001, ANN202
    response = getattr(client, method)(path, headers=headers, **kw)
    assert response.status_code in (200, 202), response.text
    job = response.json()
    return client.get(f"/api/jobs/{job['id']}", headers=headers).json()


def test_retheme_rewrites_published_posts_in_vk(client, admin_headers, vk, db):
    data = _project_with_posts(client, admin_headers, vk)
    pid = data["project"]["id"]
    job = _run(client, admin_headers, "post", f"/api/projects/{pid}/retheme", json={"brief": NEW, "scope": "all"})
    assert job["status"] == "success", job
    assert job["result"]["prepared"] == 3

    project = db.get(Project, pid)
    assert project.business_name == "Агентство дизайна Пиксель" and project.status == "active"
    assert project.brand["previous_briefs"][-1]["business_name"] == "Рекламное агентство Медиа"

    listing = client.get(f"/api/projects/{pid}/retheme", headers=admin_headers).json()
    assert listing["counts"]["proposed"] == 3
    published = [i for i in listing["items"] if i["published"]]
    draft = next(i for i in listing["items"] if not i["published"])
    assert all(i["new_text"] != i["old_text"] for i in listing["items"])
    # nothing was sent to VK yet
    assert vk.edits == []

    # edit one proposal by hand, exclude another
    client.patch(f"/api/posts/{published[0]['post_id']}/retheme", json={"text": "Свой текст про дизайн"},
                 headers=admin_headers)
    client.patch(f"/api/posts/{published[1]['post_id']}/retheme", json={"include": False}, headers=admin_headers)

    job = _run(client, admin_headers, "post", f"/api/projects/{pid}/retheme/apply", json={"keep_image": True})
    assert job["status"] == "success", job
    assert job["result"]["applied"] == 2 and job["result"]["failed"] == []
    assert len(vk.edits) == 1  # only the included published post went to VK; the draft changed locally

    db.expire_all()
    edited = db.get(Post, published[0]["post_id"])
    wall_text = next(i["text"] for i in vk.walls[-101] if i["id"] == int(edited.vk_post_id))
    assert edited.text == wall_text == "Свой текст про дизайн"
    assert edited.generation_metadata["history"][-1]["text"].startswith("Как настроить рекламу")
    assert edited.status == "published"
    skipped = db.get(Post, published[1]["post_id"])
    assert skipped.text.startswith("Как настроить рекламу")
    assert db.get(Post, draft["post_id"]).text == draft["new_text"]

    after = client.get(f"/api/projects/{pid}/retheme", headers=admin_headers).json()
    assert after["counts"] == {"proposed": 1, "applied": 2, "failed": 0}
    # leftovers can be discarded
    assert client.delete(f"/api/projects/{pid}/retheme", headers=admin_headers).json() == {"discarded": 1}


def test_vk_refusal_is_reported_and_captcha_stops(client, admin_headers, vk, db):
    data = _project_with_posts(client, admin_headers, vk, published=3, drafts=0)
    pid = data["project"]["id"]
    _run(client, admin_headers, "post", f"/api/projects/{pid}/retheme", json={"brief": NEW, "scope": "published"})
    vk.fail("wall.edit", 15, "Access denied")
    vk.fail("wall.edit", 14, "Captcha needed")
    job = _run(client, admin_headers, "post", f"/api/projects/{pid}/retheme/apply", json={})
    result = job["result"]
    assert result["applied"] == 0 and len(result["failed"]) == 2 and result["stopped"]
    listing = client.get(f"/api/projects/{pid}/retheme", headers=admin_headers).json()
    assert listing["counts"] == {"proposed": 1, "applied": 0, "failed": 2}
    assert all(i["error"] for i in listing["items"] if i["retheme_status"] == "failed")
    # a second run retries the failed ones
    job = _run(client, admin_headers, "post", f"/api/projects/{pid}/retheme/apply", json={})
    assert job["result"]["applied"] == 3


def test_edit_single_published_post_in_vk(client, admin_headers, vk, db):
    data = _project_with_posts(client, admin_headers, vk, published=1, drafts=1)
    published, draft = data["posts"]
    r = client.post(f"/api/posts/{published}/edit-vk", json={"text": "Исправленный текст"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "Исправленный текст" and vk.walls[-101][0]["text"] == "Исправленный текст"
    assert client.post(f"/api/posts/{draft}/edit-vk", json={"text": "x"}, headers=admin_headers).status_code == 422
    vk.fail("wall.edit", 15, "Access denied")
    r = client.post(f"/api/posts/{published}/edit-vk", json={"text": "Ещё"}, headers=admin_headers)
    assert r.status_code == 502 and "VK не дал изменить" in r.json()["detail"]
    db.expire_all()
    assert db.get(Post, published).text == "Исправленный текст"
