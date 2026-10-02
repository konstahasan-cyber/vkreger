"""Regression tests for issues found in code review."""
from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.db.base import utcnow
from app.models.community import Community
from app.models.content import Post
from app.models.inbox import InboxItem, Lead
from app.models.system import AIUsage
from app.services.inbox_service import claim_for_triage
from app.vk.client import VKClient
from app.vk.errors import VKNetworkError
from app.workers.tasks.inbox import triage, triage_pending
from app.workers.tasks.publishing import dispatch_due_posts
from tests.helpers import add_account, setup_project_with_community


@pytest.fixture
def project(client, admin_headers, vk):
    return setup_project_with_community(client, admin_headers, vk)


def _item(db, project, **kw) -> InboxItem:  # noqa: ANN001
    data = {"kind": "message", "vk_item_id": 1, "peer_id": 5, "from_id": 5, "text": "Сколько стоит?"} | kw
    item = InboxItem(project_id=project["id"], community_id=project["community_id"], raw={}, **data)
    db.add(item)
    db.commit()
    return item


def test_auto_reply_without_community_token_does_not_loop(client, admin_headers, db, vk, project):
    client.patch(f"/api/projects/{project['id']}", json={"auto_reply_mode": "AUTO", "auto_reply_types": ["QUESTION"]},
                 headers=admin_headers)
    community = db.get(Community, project["community_id"])
    community.community_token = None
    db.commit()
    item = _item(db, project)
    comment = _item(db, project, kind="comment", vk_item_id=2, vk_post_id=None, text="Как заказать?")
    before = db.execute(select(func.count()).select_from(AIUsage)).scalar_one()
    triage_pending()
    triage_pending()
    db.expire_all()
    assert db.get(InboxItem, item.id).reply_status == "pending_approval"
    assert db.get(InboxItem, comment.id).reply_status in ("pending_approval", "suggested")
    after = db.execute(select(func.count()).select_from(AIUsage)).scalar_one()
    assert after - before == 2  # one AI call per item, each recorded
    assert vk.messages == []


def test_ai_spend_recorded_even_if_transaction_rolls_back(db, project):
    from app.openai.agents import community_manager
    from app.openai.service import AIService
    from app.services.project_service import get_project

    community_manager.triage(AIService(db), get_project(db, project["id"]), kind="message", text="Привет")
    db.rollback()
    assert db.execute(select(func.count()).select_from(AIUsage).where(AIUsage.operation == "inbox_triage")).scalar_one() == 1


def test_triage_claim_prevents_double_processing(db, project):
    item = _item(db, project, text="Хочу заказать")
    assert claim_for_triage(db, item.id) is True
    assert claim_for_triage(db, item.id) is False
    assert triage(item.id) is None  # second run skips
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Lead)).scalar_one() == 0


def test_cost_limited_item_is_retried_later(db, project):
    from app.services.settings_service import update_runtime_settings

    update_runtime_settings(db, {"MAX_AI_COST_PER_DAY": 0.0})
    db.commit()
    item = _item(db, project, text="Хочу заказать")
    triage(item.id)
    db.expire_all()
    item = db.get(InboxItem, item.id)
    assert item.reply_status == "new" and "limit" in item.error
    update_runtime_settings(db, {"MAX_AI_COST_PER_DAY": None})
    item.updated_at = utcnow() - timedelta(hours=2)
    db.commit()
    triage_pending()
    db.expire_all()
    assert db.get(InboxItem, item.id).classification == "LEAD"


def test_cannot_delete_bound_proxy(client, admin_headers, db, vk):
    from app.models.proxy import Proxy

    proxy = Proxy(scheme="http", host="8.8.8.8", port=80, status="alive")
    db.add(proxy)
    db.commit()
    add_account(client, admin_headers, proxy_id=proxy.id)
    assert client.delete(f"/api/proxies/{proxy.id}", headers=admin_headers).status_code == 409


def test_non_json_vk_response_is_network_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(407, text="<html>Proxy Authentication Required</html>"))
    with pytest.raises(VKNetworkError):
        VKClient("t", transport=transport).call("users.get")


def test_html_error_page_marks_post_for_retry(db, vk, project):
    post = Post(project_id=project["id"], community_id=project["community_id"], text="x", status="scheduled",
                scheduled_at=utcnow() - timedelta(minutes=1), guid=uuid.uuid4().hex, attachments=[], hashtags=[],
                analytics={}, generation_metadata={})
    db.add(post)
    db.commit()
    original = vk.handle
    vk.handle = lambda request: httpx.Response(403, text="<html>blocked</html>")
    try:
        from app.vk.factory import set_transport_override

        set_transport_override(httpx.MockTransport(vk.handle))
        dispatch_due_posts()
    finally:
        vk.handle = original
    db.refresh(post)
    assert post.status == "scheduled" and post.attempts == 1 and "non-JSON" in post.last_error
