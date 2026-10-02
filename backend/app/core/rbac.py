"""Role based access control.

Roles are ordered; each role has an explicit set of permissions so the matrix can
later be moved to the database (per-organization custom roles) without touching
the endpoints, which only depend on ``Permission`` values.
"""
from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class Permission(str, Enum):
    VIEW = "view"
    MANAGE_ACCOUNTS = "manage_accounts"
    MANAGE_PROXIES = "manage_proxies"
    MANAGE_PROJECTS = "manage_projects"
    MANAGE_CONTENT = "manage_content"
    PUBLISH = "publish"
    HANDLE_INBOX = "handle_inbox"
    MANAGE_AI_SETTINGS = "manage_ai_settings"
    VIEW_LOGS = "view_logs"
    MANAGE_USERS = "manage_users"
    FORCE_AI_LIMIT = "force_ai_limit"


_OPERATOR = {
    Permission.VIEW,
    Permission.MANAGE_CONTENT,
    Permission.PUBLISH,
    Permission.HANDLE_INBOX,
}
_ADMIN = _OPERATOR | {
    Permission.MANAGE_ACCOUNTS,
    Permission.MANAGE_PROXIES,
    Permission.MANAGE_PROJECTS,
    Permission.MANAGE_AI_SETTINGS,
    Permission.VIEW_LOGS,
    Permission.FORCE_AI_LIMIT,
}

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: {Permission.VIEW},
    Role.OPERATOR: _OPERATOR,
    Role.ADMIN: _ADMIN,
    Role.OWNER: set(Permission),
}


def has_permission(role: str | Role, permission: Permission) -> bool:
    try:
        return permission in ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return False
