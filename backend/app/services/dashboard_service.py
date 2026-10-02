from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.community import Community
from app.models.content import Post
from app.models.enums import AccountStatus, LeadStatus, LogLevel, PostStatus, ProjectStatus, ProxyStatus
from app.models.inbox import InboxItem, Lead
from app.models.project import Project
from app.models.proxy import Proxy
from app.models.system import SystemLog
from app.models.vk_account import VKAccount
from app.openai.usage import CostGuard, usage_report
from app.services.settings_service import load_runtime_settings


def _count(db: Session, model, *where) -> int:  # noqa: ANN001
    return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()


def dashboard(db: Session) -> dict:
    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rs = load_runtime_settings(db)
    return {
        "projects": {
            "active": _count(db, Project, Project.status == ProjectStatus.ACTIVE.value),
            "total": _count(db, Project, Project.status != ProjectStatus.ARCHIVED.value),
            "autopilot": _count(db, Project, Project.autopilot.is_(True)),
        },
        "accounts": {
            "total": _count(db, VKAccount),
            "active": _count(db, VKAccount, VKAccount.status == AccountStatus.ACTIVE.value),
            "problems": _count(db, VKAccount, VKAccount.status.in_([AccountStatus.INVALID.value, AccountStatus.ERROR.value])),
        },
        "proxies": {
            "total": _count(db, Proxy),
            "alive": _count(db, Proxy, Proxy.status == ProxyStatus.ALIVE.value),
            "dead": _count(db, Proxy, Proxy.status == ProxyStatus.DEAD.value),
            "free": _count(db, Proxy, Proxy.status == ProxyStatus.ALIVE.value,
                           Proxy.id.not_in(select(VKAccount.proxy_id).where(VKAccount.proxy_id.is_not(None)))),
        },
        "communities": {"total": _count(db, Community),
                        "connected": _count(db, Community, Community.project_id.is_not(None))},
        "posts": {
            "published_today": _count(db, Post, Post.published_at >= day_start),
            "scheduled_today": _count(db, Post, Post.status == PostStatus.SCHEDULED.value,
                                      Post.scheduled_at >= day_start, Post.scheduled_at < day_start + timedelta(days=1)),
            "in_queue": _count(db, Post, Post.status == PostStatus.SCHEDULED.value),
            "awaiting_approval": _count(db, Post, Post.status == PostStatus.DRAFT.value, Post.scheduled_at.is_not(None)),
            "failed": _count(db, Post, Post.status == PostStatus.FAILED.value),
        },
        "errors": {
            "last_24h": _count(db, SystemLog, SystemLog.level == LogLevel.ERROR.value,
                               SystemLog.created_at >= now - timedelta(hours=24)),
        },
        "leads": {
            "new": _count(db, Lead, Lead.status == LeadStatus.NEW.value),
            "last_7_days": _count(db, Lead, Lead.created_at >= now - timedelta(days=7)),
        },
        "inbox": {"pending_approval": _count(db, InboxItem, InboxItem.reply_status == "pending_approval")},
        "ai_costs": {**usage_report(db), "limits": CostGuard(db, rs).status()},
    }
