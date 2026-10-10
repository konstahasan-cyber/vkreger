"""Networks: bulk connection of groups by community keys, different voices, network-wide repeat check."""
from __future__ import annotations

import uuid

from app.content.similarity import check_uniqueness
from app.models.content import Post
from app.models.project import Project
from app.services.network_service import parse_lines
from tests.helpers import create_project
from tests.vk_mock import COMMUNITY_TOKEN

KEY_A = "vk1.a.key-for-group-102_" + "x" * 20
KEY_B = "vk1.a.key-for-group-103_" + "y" * 20


def _groups(vk) -> None:  # noqa: ANN001
    for gid, key in ((102, KEY_A), (103, KEY_B)):
        vk.groups[gid] = {"id": gid, "name": f"Работа в городе {gid}", "screen_name": f"job{gid}", "is_admin": 0,
                          "members_count": 10}
        vk.key_groups[key] = gid


def test_parse_lines_accepts_common_formats():
    text = "\n".join([
        f"101 {COMMUNITY_TOKEN}",
        f"https://vk.com/club102;{KEY_A};Работа Казань",
        f"{KEY_B}",
        "# comment",
        "",
        "104 no-key-here",
        f"-105\t{COMMUNITY_TOKEN}",
        f"vk.com/job106 | {'a' * 85}",
    ])
    items = parse_lines(text)
    assert [(i.group, bool(i.token), i.error is None) for i in items] == [
        ("101", True, True), ("102", True, True), (None, True, True), ("104", False, False),
        ("105", True, False), ("job106", True, True),
    ]
    assert items[1].label == "Работа Казань"
    assert "этот ключ уже есть" in items[4].error
    masked = items[0].to_dict()["token"]
    assert COMMUNITY_TOKEN not in masked and masked.startswith("vk1.a.")


def test_bulk_connect_creates_projects_with_different_voices_and_posts(client, admin_headers, vk, db):
    _groups(vk)
    lines = f"101 {COMMUNITY_TOKEN}\n102 {KEY_A}\n{KEY_B}\n999 {KEY_A}x\nбез ключа"
    r = client.post("/api/networks/bulk", json={
        "network": "Кадровое агентство",
        "brief": {"business_name": "Кадровое агентство Старт", "niche": "подбор персонала", "city": "Казань"},
        "lines": lines, "days": 3, "cadence_days": 1, "post_times": ["10:00", "18:30"], "with_image": False,
        "auto_schedule": True,
    }, headers=admin_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["connected"] == 3
    bad = [x for x in data["results"] if not x["ok"]]
    assert len(bad) == 2 and all(x["error"] for x in bad)
    personas = {x["persona"] for x in data["results"] if x["ok"]}
    assert len(personas) == 3  # every group speaks with its own voice

    job = client.get(f"/api/jobs/{data['job']['id']}", headers=admin_headers).json()
    assert job["status"] == "success", job
    assert job["result"]["posts_per_group"] == 6  # 3 days × 2 times
    for project_id, child_id in job["result"]["children"].items():
        child = client.get(f"/api/jobs/{child_id}", headers=admin_headers).json()
        assert child["status"] == "success", child
        posts = db.query(Post).filter(Post.project_id == int(project_id)).all()
        assert len(posts) == 6 and all(p.status == "scheduled" for p in posts)

    # only one STRATEGIST setup for the whole network; the others share it
    from app.models.system import AIUsage

    assert db.query(AIUsage).filter(AIUsage.operation == "project_setup").count() == 1
    projects = db.query(Project).filter(Project.network == "Кадровое агентство").all()
    assert len(projects) == 3 and all(p.rubrics and p.context_summary for p in projects)
    # posting times are staggered between groups
    times = {p.id: sorted({x.scheduled_at.strftime("%H:%M") for x in db.query(Post).filter(Post.project_id == p.id)})
             for p in projects}
    assert len({tuple(v) for v in times.values()}) == 3

    overview = client.get("/api/networks/detail", params={"name": "Кадровое агентство"}, headers=admin_headers).json()
    assert len(overview["projects"]) == 3 and all(p["posts"]["scheduled"] == 6 for p in overview["projects"])
    assert client.get("/api/networks", headers=admin_headers).json() == [{"name": "Кадровое агентство", "projects": 3}]
    # the keys are stored encrypted and never returned
    assert KEY_A not in r.text and KEY_A not in str(job)


def test_generation_sees_sibling_groups(client, admin_headers, vk, db):
    _groups(vk)
    client.post("/api/networks/bulk", json={
        "network": "Сеть", "brief": {"business_name": "Агентство"}, "lines": f"101 {COMMUNITY_TOKEN}\n102 {KEY_A}",
        "days": 1, "generate": False,
    }, headers=admin_headers)
    a, b = db.query(Project).order_by(Project.id).all()
    db.add(Post(project_id=a.id, title="Как пройти собеседование", topic="Как пройти собеседование",
                text="Пять шагов к успешному собеседованию\n\nТекст", status="draft", guid=uuid.uuid4().hex,
                attachments=[], analytics={}, hashtags=[], generation_metadata={}))
    db.commit()
    report = check_uniqueness(db, b.id, title="Как пройти собеседование", topic="другое", cta=None, embedding=None,
                              window=30, semantic_threshold=0.9, title_threshold=0.75, cta_window=3,
                              sibling_ids=[a.id], opening="Пять шагов к успешному собеседованию")
    assert not report.ok
    assert any("другой группы" in r for r in report.reasons) and any("opening" in r for r in report.reasons)
    # a group outside the network is not compared
    assert check_uniqueness(db, b.id, title="Как пройти собеседование", topic="x", cta=None, embedding=None,
                            window=30, semantic_threshold=0.9, title_threshold=0.75, cta_window=3).ok

    from app.openai.agents.copywriter import compose_post  # noqa: F401
    from app.openai.context import network_posts_summary

    db.refresh(b)
    assert "Как пройти собеседование" in network_posts_summary(db, b)


def test_similar_posts_found_and_rewritten(client, admin_headers, vk, db):
    p1 = create_project(client, admin_headers, None, name="Группа 1")
    p2 = create_project(client, admin_headers, None, name="Группа 2")
    for p in (p1, p2):
        job = client.post(f"/api/projects/{p['id']}/setup", json={}, headers=admin_headers).json()
        assert client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()["status"] == "success"
    r = client.post("/api/networks/projects", json={"network": "Кадры", "project_ids": [p1["id"], p2["id"]]},
                    headers=admin_headers)
    assert r.status_code == 200, r.text
    assert len({a["persona"] for a in r.json()["added"]}) == 2
    for p in (p1, p2):
        db.add(Post(project_id=p["id"], title="Топ ошибок в резюме", topic="Ошибки в резюме",
                    text="Топ ошибок в резюме, которые мешают\n\nТекст", status="draft", guid=uuid.uuid4().hex,
                    attachments=[], analytics={}, hashtags=[], generation_metadata={"angle": "a"},
                    category="educational"))
    db.commit()
    similar = client.get("/api/networks/similar", params={"name": "Кадры"}, headers=admin_headers).json()
    assert similar["to_rewrite"] == 1 and "одинаковое начало" in similar["pairs"][0]["reasons"]

    job = client.post("/api/networks/dedupe", json={"network": "Кадры"}, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "success" and len(job["result"]["rewritten"]) == 1, job
    rewritten = db.get(Post, job["result"]["rewritten"][0])
    db.refresh(rewritten)
    assert rewritten.title != "Топ ошибок в резюме" and rewritten.generation_metadata["rewrites"] == 1
    assert client.get("/api/networks/similar", params={"name": "Кадры"}, headers=admin_headers).json()["to_rewrite"] == 0


def test_cadence_with_several_times_per_day():
    from types import SimpleNamespace

    from app.workers.tasks.ai_jobs import plan_cadence, posts_in_period, stagger_times

    project = SimpleNamespace(timezone="Europe/Moscow", posting_times=["10:00"])
    slots = plan_cadence(project, 5, 2, "19:00,10:00", "2030-01-01")
    local = [s.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Moscow")).strftime("%d %H:%M") for s in slots]
    assert local == ["01 10:00", "01 19:00", "03 10:00", "03 19:00", "05 10:00"]
    assert posts_in_period(14, 1, 1) == 14 and posts_in_period(14, 2, 2) == 14 and posts_in_period(3, 2, 1) == 2
    assert stagger_times(["10:00", "23:58"], 4) == "10:04,00:02"
