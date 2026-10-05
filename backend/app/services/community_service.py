"""VK communities: connect existing / create new, apply settings, pinned post, event delivery."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.db.base import utcnow
from app.models.community import Community
from app.models.content import Post
from app.models.enums import EventMode, LogLevel, PostStatus, ProjectStatus
from app.models.project import Project
from app.models.vk_account import VKAccount
from app.services.audit import syslog
from app.vk.errors import VKAPIError, VKError
from app.vk.factory import client_for_account, client_for_community

VK_TITLE_MAX = 48
VK_STATUS_MAX = 139


def get_community(db: Session, community_id: int) -> Community:
    community = db.get(Community, community_id)
    if community is None:
        raise NotFoundError(f"Сообщество #{community_id} не найдено")
    return community


def _require_account(project: Project) -> VKAccount:
    if project.vk_account is None:
        raise ValidationAppError("Сначала выберите аккаунт VK в настройках проекта")
    return project.vk_account


def _upsert_from_vk(db: Session, group: dict, account: VKAccount) -> Community:
    community = db.execute(select(Community).where(Community.vk_group_id == int(group["id"]))).scalar_one_or_none()
    if community is None:
        community = Community(vk_group_id=int(group["id"]), name=group.get("name") or f"club{group['id']}",
                              settings={}, longpoll_server={})
        db.add(community)
    community.name = group.get("name") or community.name
    community.screen_name = group.get("screen_name") or community.screen_name
    community.description = group.get("description", community.description)
    community.photo_url = group.get("photo_200") or group.get("photo_100") or community.photo_url
    community.members_count = group.get("members_count", community.members_count)
    community.is_admin = bool(group.get("is_admin", 1))
    community.account_id = account.id
    community.account = account
    community.last_synced_at = utcnow()
    db.flush()
    return community


def sync_account_communities(db: Session, account: VKAccount) -> list[Community]:
    with client_for_account(account) as client:
        groups = client.get_admin_groups()
    account.groups_cache = [{"id": g["id"], "name": g.get("name"), "screen_name": g.get("screen_name"),
                             "members_count": g.get("members_count")} for g in groups]
    return [_upsert_from_vk(db, g, account) for g in groups]


def connect_community(db: Session, project: Project, vk_group_id: int, community_token: str | None = None) -> Community:
    account = _require_account(project)
    if project.community and project.community.vk_group_id != vk_group_id:
        raise ConflictError("У проекта уже есть другое сообщество — сначала отключите его")
    with client_for_account(account) as client:
        group = client.get_group(vk_group_id)
    if not group.get("is_admin"):
        raise ValidationAppError("Выбранный аккаунт не является администратором этого сообщества")
    community = _upsert_from_vk(db, group, account)
    if community.project_id and community.project_id != project.id:
        raise ConflictError(f"Это сообщество уже подключено к проекту #{community.project_id}")
    community.project_id = project.id
    community.project = project
    if community_token:
        community.community_token = community_token.strip()
    db.query(Post).filter(Post.project_id == project.id, Post.community_id.is_(None)).update(
        {Post.community_id: community.id}, synchronize_session=False)
    db.flush()
    return community


def create_community(db: Session, project: Project, *, title: str, description: str | None,
                     public_category: int | None = None, subtype: int | None = None) -> Community:
    """Create a public page through groups.create (official API, explicit user confirmation)."""
    account = _require_account(project)
    if project.community:
        raise ConflictError("У проекта уже есть сообщество")
    title = title.strip()[:VK_TITLE_MAX]
    if not title:
        raise ValidationAppError("Укажите название сообщества")
    with client_for_account(account) as client:
        created = client.create_group(title, description, type_="public", public_category=public_category,
                                      subtype=subtype)
        group = client.get_group(created["id"])
    group.setdefault("is_admin", 1)
    community = _upsert_from_vk(db, group, account)
    community.created_by_app = True
    community.project_id = project.id
    community.project = project
    db.flush()
    return community


def apply_settings(db: Session, community: Community, *, description: str | None = None, status: str | None = None,
                   website: str | None = None, title: str | None = None) -> dict:
    """Fill community settings (groups.edit + status.set). Returns per-step results."""
    results: dict[str, str] = {}
    with client_for_community(community, prefer_community_token=False) as client:
        fields = {}
        if title:
            fields["title"] = title.strip()[:VK_TITLE_MAX]
        if description is not None:
            fields["description"] = description
        if website:
            fields["website"] = website
        if fields:
            try:
                client.edit_group(community.vk_group_id, **fields)
                results["groups.edit"] = "ok"
                community.description = description if description is not None else community.description
                community.name = fields.get("title", community.name)
            except VKAPIError as exc:
                results["groups.edit"] = f"error {exc.code}: {exc.message}"
        if status:
            try:
                client.set_status(community.vk_group_id, status.strip()[:VK_STATUS_MAX])
                results["status.set"] = "ok"
            except VKAPIError as exc:
                results["status.set"] = f"error {exc.code}: {exc.message}"
    db.flush()
    return results


def create_pinned_post(db: Session, project: Project, *, title: str, text: str) -> Post:
    import uuid

    from app.services.publishing_service import publish_post_now

    community = project.community
    if community is None:
        raise ValidationAppError("Сначала подключите сообщество")
    post = Post(project_id=project.id, community_id=community.id, title=title[:500], text=text, category="pinned",
                topic=title, status=PostStatus.APPROVED.value, guid=uuid.uuid4().hex, attachments=[], hashtags=[],
                analytics={}, generation_metadata={"operation": "pinned_post"}, is_pinned=True)
    db.add(post)
    db.flush()
    publish_post_now(db, post)
    if post.vk_post_id:
        try:
            with client_for_community(community, prefer_community_token=False) as client:
                client.wall_pin(community.vk_group_id, post.vk_post_id)
            community.pinned_post_id = post.vk_post_id
        except VKError as exc:
            syslog(db, LogLevel.WARNING, "community", f"wall.pin failed: {exc}", project_id=project.id)
    db.flush()
    return post


def setup_events(db: Session, community: Community, mode: EventMode) -> dict:
    """Enable delivery of comments and messages via Callback API or Bots Long Poll API."""
    if mode == EventMode.NONE:
        community.event_mode = EventMode.NONE.value
        db.flush()
        return {"mode": "none"}
    if not community.community_token and mode == EventMode.LONGPOLL:
        raise ValidationAppError("Для Long Poll нужен ключ доступа сообщества")
    with client_for_community(community) as client:
        if mode == EventMode.CALLBACK:
            community.callback_secret = community.callback_secret or secrets.token_urlsafe(24)
            community.confirmation_code = client.get_callback_confirmation_code(community.vk_group_id)
            db.flush()
            url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{settings.API_PREFIX}/vk/callback/{community.id}"
            if not community.callback_server_id:
                community.callback_server_id = client.add_callback_server(
                    community.vk_group_id, url, "vkreger", community.callback_secret)
            client.set_callback_settings(community.vk_group_id, community.callback_server_id)
            community.event_mode = EventMode.CALLBACK.value
            result = {"mode": "callback", "url": url, "server_id": community.callback_server_id}
        else:
            client.set_long_poll_settings(community.vk_group_id)
            community.event_mode = EventMode.LONGPOLL.value
            community.longpoll_server = {}
            result = {"mode": "longpoll"}
    db.flush()
    return result


def activate_project(db: Session, project: Project) -> None:
    if project.status in (ProjectStatus.DRAFT.value, ProjectStatus.ANALYZING.value, ProjectStatus.PROPOSAL_READY.value):
        project.status = ProjectStatus.ACTIVE.value
    db.flush()
