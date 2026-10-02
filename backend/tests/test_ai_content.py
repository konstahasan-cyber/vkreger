from __future__ import annotations

import pytest

from app.content.generator import generate_post
from app.core.exceptions import CostLimitExceeded
from app.models.system import AIUsage
from app.openai.fake import FakeProvider
from app.openai.provider import LLMResult, set_provider_override
from app.openai.service import AIService
from app.services.project_service import get_project
from app.services.settings_service import update_runtime_settings
from tests.helpers import setup_project_with_community


class RepetitiveProvider(FakeProvider):
    """Returns the same post first; a different one once asked to avoid repeats."""

    def __init__(self):
        self.compose_calls = 0

    def complete_json(self, **kwargs) -> LLMResult:
        result = super().complete_json(**kwargs)
        if kwargs["schema_name"] == "post_compose":
            self.compose_calls += 1
            if "НЕ повторяй" in kwargs["input_text"]:
                result.data.update(title="Совсем другая тема про обжарку", topic="Обжарка зерна дома",
                                   cta="Пишите в личку", text="Про обжарку дома.")
            else:
                result.data.update(title="Как выбрать кофе", topic="Как выбрать кофе", cta="Закажите сейчас",
                                   text="Как выбрать кофе: советы.")
        return result


@pytest.fixture
def project(client, admin_headers, vk):
    return setup_project_with_community(client, admin_headers, vk)


def test_similar_post_is_regenerated(db, project):
    provider = RepetitiveProvider()
    set_provider_override(provider)
    try:
        p = get_project(db, project["id"])
        first = generate_post(db, p, topic="Как выбрать кофе", rubric_code="educational", with_image=False)
        db.commit()
        second = generate_post(db, p, topic="Как выбрать кофе", rubric_code="educational", with_image=False)
        db.commit()
    finally:
        set_provider_override(None)
    assert first.title == "Как выбрать кофе"
    assert second.title == "Совсем другая тема про обжарку"
    attempts = second.generation_metadata["uniqueness_attempts"]
    assert attempts[0]["ok"] is False and attempts[-1]["ok"] is True
    assert any("similar" in r for r in attempts[0]["reasons"])
    assert provider.compose_calls == 3


def test_context_is_compact(db, project):
    captured = []

    class Spy(FakeProvider):
        def complete_json(self, **kwargs):
            captured.append(kwargs)
            return super().complete_json(**kwargs)

    set_provider_override(Spy())
    try:
        p = get_project(db, project["id"])
        for i in range(5):
            generate_post(db, p, topic=f"Тема номер {i} про кофе {i * 7}", with_image=False)
            db.commit()
    finally:
        set_provider_override(None)
    last = captured[-1]["input_text"]
    for block in ("<project_context>", "<brand_context>", "<content_rules>", "<recent_posts_summary>", "<task>"):
        assert block in last
    # recent posts are summarised as one line each, not full texts
    assert "Подробный разбор" not in last.split("<recent_posts_summary>")[1]
    assert captured[-1]["cache_key"].startswith("vkreger:post_compose:")
    assert "specialty кофе" not in last  # raw brief replaced by context_summary


def test_cost_limits_block_automatic_tasks(client, admin_headers, viewer_headers, db, project):
    update_runtime_settings(db, {"MAX_AI_COST_PER_PROJECT_DAY": 0.5})
    db.add(AIUsage(model="gpt-5.4-mini", operation="post_compose", estimated_cost=0.6, project_id=project["id"]))
    db.commit()
    ai = AIService(db)
    with pytest.raises(CostLimitExceeded):
        ai.guard.check(project["id"], automatic=True)
    with pytest.raises(CostLimitExceeded):
        ai.guard.check(project["id"], automatic=False)
    ai.guard.check(project["id"], automatic=False, force=True)
    ai.guard.check(None, automatic=True)  # global limit (10$) is not exceeded

    job = client.post("/api/posts/generate", json={"project_id": project["id"]}, headers=admin_headers).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=admin_headers).json()
    assert job["status"] == "failed" and "limit" in job["error"]
    forced = client.post("/api/posts/generate", json={"project_id": project["id"], "force": True},
                         headers=admin_headers).json()
    assert client.get(f"/api/jobs/{forced['id']}", headers=admin_headers).json()["status"] == "success"
    limits = client.get(f"/api/ai/limits?project_id={project['id']}", headers=admin_headers).json()
    assert limits["project_exceeded"] is True

    from app.services.queue_service import fill_queue

    p = get_project(db, project["id"])
    result = fill_queue(db, p, automatic=True)
    assert result["skipped"] == "cost limit"


def test_ai_settings_api(client, admin_headers, viewer_headers):
    r = client.put("/api/ai/settings", json={"AI_DEFAULT_MODEL": "gpt-5.4-nano",
                                             "AI_MODEL_OVERRIDES": {"project_setup": "gpt-5.4"}}, headers=admin_headers)
    assert r.status_code == 200
    values = client.get("/api/ai/settings", headers=admin_headers).json()["values"]
    assert values["AI_DEFAULT_MODEL"] == "gpt-5.4-nano"
    assert client.put("/api/ai/settings", json={"OPENAI_API_KEY": "x"}, headers=admin_headers).status_code == 422
    assert client.put("/api/ai/settings", json={"AI_DEFAULT_MODEL": "x"}, headers=viewer_headers).status_code == 403


def test_model_override_is_used(db, project):
    seen = []

    class Spy(FakeProvider):
        def complete_json(self, **kwargs):
            seen.append((kwargs["schema_name"], kwargs["model"]))
            return super().complete_json(**kwargs)

    update_runtime_settings(db, {"AI_MODEL_OVERRIDES": {"post_compose": "gpt-5.4"}})
    db.commit()
    set_provider_override(Spy())
    try:
        generate_post(db, get_project(db, project["id"]), topic="Тема", with_image=False)
    finally:
        set_provider_override(None)
    assert ("post_compose", "gpt-5.4") in seen


def test_fill_queue_respects_slots_and_autoapprove(client, admin_headers, db, vk):
    project = setup_project_with_community(client, admin_headers, vk, posts_per_day=2, auto_approve=True,
                                           posting_times=["09:00", "18:00"])
    from app.services.queue_service import fill_queue

    p = get_project(db, project["id"])
    result = fill_queue(db, p, horizon_days=2, max_new=10, automatic=True)
    db.commit()
    assert 3 <= len(result["created"]) <= 6
    posts = client.get(f"/api/posts?project_id={p.id}&status=scheduled", headers=admin_headers).json()["items"]
    times = [x["scheduled_at"] for x in posts]
    assert len(times) == len(set(times))
    again = fill_queue(db, p, horizon_days=2, max_new=10, automatic=True)
    assert again["created"] == [] and again["skipped"] == "queue is full"
