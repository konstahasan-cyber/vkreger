from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.analytics.analyst_service import run_review
from app.analytics.collector import collect_recent
from app.db.base import utcnow
from app.models.community import Community
from app.models.content import Post
from app.services.project_service import get_project
from tests.helpers import setup_project_with_community


@pytest.fixture
def project(client, admin_headers, vk):
    return setup_project_with_community(client, admin_headers, vk)


def _enable_callback(client, headers, project):  # noqa: ANN001
    r = client.post(f"/api/communities/{project['community_id']}/events", json={"mode": "callback"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _secret(db, community_id):  # noqa: ANN001
    return db.get(Community, community_id).callback_secret


def test_callback_confirmation_and_secret(client, admin_headers, db, vk, project):
    info = _enable_callback(client, admin_headers, project)
    assert info["url"] == f"https://panel.example.com/api/vk/callback/{project['community_id']}"
    url = f"/api/vk/callback/{project['community_id']}"
    assert client.post(url, json={"type": "confirmation", "group_id": 101}).text == "abc123"
    bad = client.post(url, json={"type": "message_new", "group_id": 101, "secret": "wrong", "object": {}})
    assert bad.status_code == 403
    assert client.post(url, json={"type": "confirmation", "group_id": 999}).status_code == 404


def test_lead_message_creates_lead_and_waits_for_approval(client, admin_headers, db, vk, project):
    _enable_callback(client, admin_headers, project)
    secret = _secret(db, project["community_id"])
    event = {"type": "message_new", "group_id": 101, "secret": secret, "event_id": "e1",
             "object": {"message": {"id": 11, "from_id": 555, "peer_id": 555, "text": "Хочу заказать кофе на офис"}}}
    url = f"/api/vk/callback/{project['community_id']}"
    assert client.post(url, json=event).text == "ok"
    assert client.post(url, json=event).text == "ok"  # VK retry → deduplicated
    items = client.get("/api/messages", headers=admin_headers).json()
    assert items["total"] == 1
    item = items["items"][0]
    assert item["classification"] == "LEAD" and item["reply_status"] == "pending_approval"
    leads = client.get("/api/leads", headers=admin_headers).json()
    assert leads["total"] == 1 and leads["items"][0]["vk_user_id"] == 555
    notes = client.get("/api/notifications?unread=true", headers=admin_headers).json()
    assert notes[0]["kind"] == "lead"
    sent = client.post(f"/api/messages/{item['id']}/reply", json={}, headers=admin_headers).json()
    assert sent["reply_status"] == "sent"
    assert vk.messages[0]["peer_id"] == "555"
    assert client.post(f"/api/messages/{item['id']}/reply", json={}, headers=admin_headers).status_code == 422


def test_auto_mode_answers_questions_on_comments(client, admin_headers, db, vk, project):
    client.patch(f"/api/projects/{project['id']}", json={"auto_reply_mode": "AUTO", "auto_reply_types": ["QUESTION"]},
                 headers=admin_headers)
    _enable_callback(client, admin_headers, project)
    secret = _secret(db, project["community_id"])
    url = f"/api/vk/callback/{project['community_id']}"
    question = {"type": "wall_reply_new", "group_id": 101, "secret": secret,
                "object": {"id": 71, "from_id": 9, "post_id": 3, "owner_id": -101, "text": "Сколько стоит капучино?"}}
    complaint = {"type": "wall_reply_new", "group_id": 101, "secret": secret,
                 "object": {"id": 72, "from_id": 9, "post_id": 3, "owner_id": -101, "text": "Ужас, всё плохо"}}
    own = {"type": "wall_reply_new", "group_id": 101, "secret": secret,
           "object": {"id": 73, "from_id": -101, "post_id": 3, "owner_id": -101, "text": "Наш ответ"}}
    for event in (question, complaint, own):
        client.post(url, json=event)
    items = {i["vk_item_id"]: i for i in client.get("/api/messages", headers=admin_headers).json()["items"]}
    assert set(items) == {71, 72}
    assert items[71]["reply_status"] == "sent" and vk.comments[0]["reply_to_comment"] == "71"
    assert items[72]["classification"] == "NEGATIVE" and items[72]["reply_status"] == "pending_approval"


def test_off_mode_only_suggests(client, admin_headers, db, vk, project):
    client.patch(f"/api/projects/{project['id']}", json={"auto_reply_mode": "OFF"}, headers=admin_headers)
    _enable_callback(client, admin_headers, project)
    client.post(f"/api/vk/callback/{project['community_id']}", json={
        "type": "message_new", "group_id": 101, "secret": _secret(db, project["community_id"]),
        "object": {"message": {"id": 1, "from_id": 5, "peer_id": 5, "text": "Где вы находитесь?"}}})
    item = client.get("/api/messages", headers=admin_headers).json()["items"][0]
    assert item["reply_status"] == "suggested" and item["suggested_reply"]
    assert vk.messages == []


def test_longpoll_cycle(client, admin_headers, db, vk, project):
    r = client.post(f"/api/communities/{project['community_id']}/events", json={"mode": "longpoll"},
                    headers=admin_headers)
    assert r.json()["mode"] == "longpoll"
    from app.services.inbox_service import poll_longpoll

    community = db.get(Community, project["community_id"])
    assert poll_longpoll(db, community, wait=1) == 0
    db.commit()
    assert db.get(Community, community.id).longpoll_server["ts"] == "2"


def test_analytics_collection_and_analyst(client, admin_headers, db, vk, project):
    for i in range(12):
        post = Post(project_id=project["id"], community_id=project["community_id"], title=f"Пост {i}", text=f"t{i}",
                    category="faq" if i % 2 else "case", status="published", vk_post_id=i + 1,
                    published_at=utcnow(), guid=uuid.uuid4().hex, attachments=[], hashtags=[], analytics={},
                    generation_metadata={})
        db.add(post)
    db.commit()
    totals = collect_recent(db)
    assert totals == {"communities": 1, "posts": 12, "errors": 0}
    stats = client.get(f"/api/analytics/projects/{project['id']}", headers=admin_headers).json()
    assert stats["posts_count"] == 12 and stats["avg_views"] > 0
    assert stats["total_clicks"] == 36
    assert {c["category"] for c in stats["by_category"]} == {"faq", "case"}
    some_post = db.execute(select(Post).where(Post.vk_post_id == 3)).scalar_one()
    history = client.get(f"/api/analytics/posts/{some_post.id}/history", headers=admin_headers).json()
    assert history[0]["views"] == 300

    p = get_project(db, project["id"])
    result = run_review(db, p)
    db.commit()
    assert "review" in result
    # the second automatic review is skipped: minimum interval between strategy revisions
    assert run_review(db, p) == {"skipped": "interval"}
    plan = client.get(f"/api/projects/{project['id']}/plan", headers=admin_headers).json()
    assert any(item["angle"] == "idea from ANALYST" for item in plan)
    overview = client.get("/api/analytics/overview", headers=admin_headers).json()
    assert overview[0]["posts"] == 12


def test_dashboard(client, admin_headers, vk, project):
    data = client.get("/api/dashboard", headers=admin_headers).json()
    assert data["accounts"]["active"] == 1
    assert data["communities"]["connected"] == 1
    assert data["ai_costs"]["today"] > 0
    assert "limits" in data["ai_costs"]
