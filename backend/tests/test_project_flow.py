from __future__ import annotations

from datetime import timedelta

from app.db.base import utcnow
from app.models.content import Post
from app.workers.tasks.publishing import dispatch_due_posts
from tests.helpers import add_account, create_project, setup_project_with_community


def test_full_wizard_create_community(client, admin_headers, vk):
    account = add_account(client, admin_headers)
    project = create_project(client, admin_headers, account["id"])
    pid = project["id"]

    assert client.get(f"/api/projects/{pid}/preview", headers=admin_headers).status_code == 409
    job = client.post(f"/api/projects/{pid}/setup", json={}, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job

    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["status"] == "proposal_ready"
    assert detail["context_summary"]
    assert len(detail["rubrics"]) >= 5
    assert detail["strategy_version"] == 1

    preview = client.get(f"/api/projects/{pid}/preview", headers=admin_headers).json()
    assert len(preview["name_options"]) == 5
    assert preview["pinned_post"]["text"]

    response = client.post(f"/api/projects/{pid}/community/create", json={
        "title": preview["name_options"][0], "description": preview["description"], "status": preview["status"],
        "pinned_post": preview["pinned_post"], "first_queue": True, "queue_size": 3,
    }, headers=admin_headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["community"]["created_by_app"] is True
    launch = client.get(f"/api/jobs/{data['job']['id']}", headers=admin_headers).json()
    assert launch["status"] == "success", launch
    assert launch["result"]["settings"]["status.set"] == "ok"
    assert len(launch["result"]["queue"]["created"]) == 3

    methods = vk.methods()
    assert "groups.create" in methods and "groups.edit" in methods and "wall.pin" in methods
    gid = data["community"]["vk_group_id"]
    assert vk.pinned[-gid] == launch["result"]["pinned_post"]["vk_post_id"]

    detail = client.get(f"/api/projects/{pid}", headers=admin_headers).json()
    assert detail["status"] == "active"
    plan = client.get(f"/api/projects/{pid}/plan", headers=admin_headers).json()
    assert any(item["status"] == "used" for item in plan)

    drafts = client.get(f"/api/posts?project_id={pid}&status=draft", headers=admin_headers).json()
    assert drafts["total"] == 3
    post = drafts["items"][0]
    assert post["image_url"] and post["image_prompt"]
    assert post["generation_metadata"]["uniqueness_attempts"]

    usage = client.get("/api/ai/usage", headers=admin_headers).json()
    operations = {row["operation"] for row in usage["by_operation"]}
    assert {"project_setup", "content_plan", "post_compose", "embedding", "image_generate"} <= operations


def test_approve_schedule_publish_with_image(client, admin_headers, vk, db):
    project = setup_project_with_community(client, admin_headers, vk)
    job = client.post("/api/posts/generate", json={"project_id": project["id"], "count": 2}, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    post_ids = job["result"]["posts"]

    approved = client.post(f"/api/posts/{post_ids[0]}/approve", headers=admin_headers).json()
    assert approved["status"] == "scheduled" and approved["scheduled_at"]

    # make it due and run the dispatcher (Celery eager mode)
    post = db.get(Post, post_ids[0])
    post.scheduled_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert dispatch_due_posts() == [post_ids[0]]
    published = client.get(f"/api/posts/{post_ids[0]}", headers=admin_headers).json()
    assert published["status"] == "published", published
    assert published["vk_post_id"]
    assert published["attachments"][0] == "photo-101_777"
    wall_post = [p for m, p in vk.calls if m == "wall.post"][-1]
    assert wall_post["guid"] and wall_post["from_group"] == "1" and wall_post["owner_id"] == "-101"
    assert vk.uploads == 1
    # the dispatcher never picks it again
    assert dispatch_due_posts() == []

    calendar = client.get("/api/calendar", params={"date_from": (utcnow() - timedelta(days=1)).isoformat(),
                                                   "date_to": (utcnow() + timedelta(days=30)).isoformat()},
                          headers=admin_headers).json()
    assert any(item["id"] == post_ids[0] for item in calendar)


def test_manual_post_and_edit_rules(client, admin_headers, vk):
    project = setup_project_with_community(client, admin_headers, vk)
    post = client.post("/api/posts", json={"project_id": project["id"], "text": "Ручной пост"},
                       headers=admin_headers).json()
    edited = client.patch(f"/api/posts/{post['id']}", json={"text": "Новый текст"}, headers=admin_headers).json()
    assert edited["text"] == "Новый текст"
    published = client.post(f"/api/posts/{post['id']}/publish-now", headers=admin_headers).json()
    assert published["status"] == "published"
    assert client.patch(f"/api/posts/{post['id']}", json={"text": "x"}, headers=admin_headers).status_code == 409
    assert client.post(f"/api/posts/{post['id']}/publish-now", headers=admin_headers).json()["vk_post_id"] == published["vk_post_id"]
    assert len([m for m in vk.methods() if m == "wall.post"]) == 1


def test_project_validation(client, admin_headers, vk):
    bad = client.post("/api/projects", json={"name": "x", "business_name": "y", "posting_times": ["25:00"]},
                      headers=admin_headers)
    assert bad.status_code == 422
    bad = client.post("/api/projects", json={"name": "x", "business_name": "y", "vk_account_id": 999},
                      headers=admin_headers)
    assert bad.status_code == 422


def test_connect_requires_admin(client, admin_headers, vk):
    vk.groups[202] = {"id": 202, "name": "Not mine", "is_admin": 0}
    account = add_account(client, admin_headers)
    project = create_project(client, admin_headers, account["id"])
    r = client.post(f"/api/projects/{project['id']}/community/connect", json={"vk_group_id": 202}, headers=admin_headers)
    assert r.status_code == 422


def test_duplicate_post(client, admin_headers, vk, db):
    project = setup_project_with_community(client, admin_headers, vk)
    job = client.post("/api/posts/generate", json={"project_id": project["id"]}, headers=admin_headers).json()
    original_id = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()["result"]["posts"][0]
    published = client.post(f"/api/posts/{original_id}/publish-now", headers=admin_headers).json()
    assert published["status"] == "published" and published["attachments"]

    copy = client.post(f"/api/posts/{original_id}/duplicate", headers=admin_headers).json()
    assert copy["id"] != original_id and copy["status"] == "draft"
    assert copy["text"] == published["text"] and copy["title"] == published["title"]
    assert copy["category"] == published["category"]
    assert copy["image_url"] and copy["image_url"] != published["image_url"]
    assert copy["attachments"] == [] and copy["vk_post_id"] is None
    assert copy["generation_metadata"]["copied_from"] == original_id
    again = client.post(f"/api/posts/{copy['id']}/publish-now", headers=admin_headers).json()
    assert again["status"] == "published" and again["vk_post_id"] != published["vk_post_id"]


def test_generate_with_cadence_and_approve_all(client, admin_headers, vk):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    project = setup_project_with_community(client, admin_headers, vk)
    tomorrow = (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(days=1)).date()
    job = client.post("/api/posts/generate", json={"project_id": project["id"], "count": 3, "cadence_days": 2,
                                                   "post_time": "18:30", "start_date": tomorrow.isoformat(),
                                                   "with_image": False}, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    posts = sorted((client.get(f"/api/posts/{i}", headers=admin_headers).json() for i in job["result"]["posts"]),
                   key=lambda p: p["scheduled_at"])
    local = [datetime.fromisoformat(p["scheduled_at"]).astimezone(ZoneInfo("Europe/Moscow")) for p in posts]
    assert [d.date() for d in local] == [tomorrow + timedelta(days=2 * i) for i in range(3)]
    assert all((d.hour, d.minute) == (18, 30) for d in local)
    assert all(p["status"] == "draft" and not p["image_url"] for p in posts)

    extra = client.post("/api/posts", json={"project_id": project["id"], "text": "без времени"}, headers=admin_headers).json()
    r = client.post("/api/posts/approve-all", json={"project_id": project["id"]}, headers=admin_headers).json()
    assert r["approved"] == 4 and r["errors"] == []
    after = [client.get(f"/api/posts/{p['id']}", headers=admin_headers).json() for p in posts]
    assert [p["scheduled_at"] for p in after] == [p["scheduled_at"] for p in posts]  # planned times kept
    assert all(p["status"] == "scheduled" for p in after)
    extra = client.get(f"/api/posts/{extra['id']}", headers=admin_headers).json()
    assert extra["status"] == "scheduled" and extra["scheduled_at"] not in {p["scheduled_at"] for p in after}


def test_export_posts_in_order(client, admin_headers, vk):
    import csv
    import io

    project = setup_project_with_community(client, admin_headers, vk)
    ids = []
    for text in ("Первый пост", "Второй пост"):
        p = client.post("/api/posts", json={"project_id": project["id"], "text": text}, headers=admin_headers).json()
        client.post(f"/api/posts/{p['id']}/publish-now", headers=admin_headers)
        ids.append(p["id"])
    r = client.get(f"/api/posts/export?project_id={project['id']}&status=published", headers=admin_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][0] == "№" and [row[6] for row in rows[1:]] == ["Первый пост", "Второй пост"]
    assert rows[1][7].startswith("https://vk.com/wall-101_")
    txt = client.get(f"/api/posts/export?project_id={project['id']}&fmt=txt", headers=admin_headers).text
    assert txt.index("Первый пост") < txt.index("Второй пост")
    assert client.get("/api/posts/export").status_code == 401
