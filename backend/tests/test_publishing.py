from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.config import settings
from app.db.base import utcnow
from app.models.content import Post
from app.services.publishing_service import claim_due_posts, publish_claimed, recover_stuck
from app.workers.tasks.publishing import dispatch_due_posts
from tests.helpers import setup_project_with_community


def _due_post(db, project, text="Пост для публикации") -> Post:  # noqa: ANN001
    post = Post(project_id=project["id"], community_id=project["community_id"], title="t", text=text, category="faq",
                status="scheduled", scheduled_at=utcnow() - timedelta(minutes=1), guid=uuid.uuid4().hex,
                attachments=[], hashtags=[], analytics={}, generation_metadata={})
    db.add(post)
    db.commit()
    return post


@pytest.fixture
def project(client, admin_headers, vk):
    return setup_project_with_community(client, admin_headers, vk)


def test_retry_then_success_without_duplicates(db, vk, project):
    post = _due_post(db, project)
    vk.fail("wall.post", 10, "Internal server error")
    dispatch_due_posts()
    db.refresh(post)
    assert post.status == "scheduled" and post.attempts == 1 and "10" in post.last_error
    assert post.scheduled_at > utcnow()
    post.scheduled_at = utcnow() - timedelta(seconds=1)
    db.commit()
    dispatch_due_posts()
    db.refresh(post)
    assert post.status == "published" and post.attempts == 2 and post.last_error is None
    assert len(vk.walls[-101]) == 1


def test_fatal_error_fails_immediately(db, vk, project):
    post = _due_post(db, project)
    vk.fail("wall.post", 214, "Access to adding post denied", times=2)  # community key, then account
    dispatch_due_posts()
    db.refresh(post)
    assert post.status == "failed" and post.attempts == 1


def test_captcha_is_not_bypassed(db, vk, project):
    post = _due_post(db, project)
    vk.fail("wall.post", 14, "Captcha needed")
    dispatch_due_posts()
    db.refresh(post)
    assert post.status == "failed"
    assert [m for m in vk.methods() if m == "wall.post"] == ["wall.post"]


def test_gives_up_after_max_attempts(db, vk, project):
    post = _due_post(db, project)
    vk.fail("wall.post", 10, "Internal", times=settings.PUBLISH_MAX_ATTEMPTS)
    for _ in range(settings.PUBLISH_MAX_ATTEMPTS):
        db.refresh(post)
        post.scheduled_at = utcnow() - timedelta(seconds=1)
        db.commit()
        dispatch_due_posts()
    db.refresh(post)
    assert post.status == "failed" and post.attempts == settings.PUBLISH_MAX_ATTEMPTS


def test_claim_is_exclusive(db, project):
    post = _due_post(db, project)
    assert claim_due_posts(db) == [post.id]
    assert claim_due_posts(db) == []


def test_vk_guid_prevents_duplicate_on_lost_response(db, vk, project):
    """Simulate: VK created the post but the worker crashed before saving vk_post_id."""
    post = _due_post(db, project)
    vk.m_wall_post({"owner_id": "-101", "message": post.text, "guid": post.guid})
    claim_due_posts(db)
    db.refresh(post)
    publish_claimed(db, post)
    db.commit()
    assert post.status == "published"
    assert len(vk.walls[-101]) == 1


def test_recover_stuck_post_found_on_wall(db, vk, project):
    post = _due_post(db, project, text="Уникальный текст поста")
    vk.m_wall_post({"owner_id": "-101", "message": "Уникальный текст поста"})
    post.status = "publishing"
    post.publishing_started_at = utcnow() - timedelta(minutes=30)
    other = _due_post(db, project, text="Не опубликован")
    other.status = "publishing"
    other.publishing_started_at = utcnow() - timedelta(minutes=30)
    db.commit()
    assert sorted(recover_stuck(db)) == sorted([post.id, other.id])
    db.commit()
    db.refresh(post)
    db.refresh(other)
    assert post.status == "published" and post.vk_post_id == 1
    assert other.status == "scheduled"


def test_failed_post_retry_endpoint(client, admin_headers, db, vk, project):
    post = _due_post(db, project)
    vk.fail("wall.post", 214, times=2)
    dispatch_due_posts()
    r = client.post(f"/api/posts/{post.id}/retry", headers=admin_headers).json()
    assert r["status"] == "scheduled" and r["attempts"] == 0
    logs = client.get("/api/logs/system?source=publishing", headers=admin_headers).json()
    assert any("214" in row["message"] for row in logs["items"])
