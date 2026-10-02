"""Import all models so that Alembic and ``Base.metadata`` see every table."""
from app.models.analytics import PostStatSnapshot
from app.models.community import Community
from app.models.content import ContentPlanItem, Post, Rubric, Strategy
from app.models.inbox import InboxItem, Lead
from app.models.project import Project
from app.models.proxy import Proxy
from app.models.system import AIUsage, AppSetting, AuditLog, Job, Notification, SystemLog
from app.models.user import User
from app.models.vk_account import VKAccount

__all__ = [
    "AIUsage",
    "AppSetting",
    "AuditLog",
    "Community",
    "ContentPlanItem",
    "InboxItem",
    "Job",
    "Lead",
    "Notification",
    "Post",
    "PostStatSnapshot",
    "Project",
    "Proxy",
    "Rubric",
    "Strategy",
    "SystemLog",
    "User",
    "VKAccount",
]
