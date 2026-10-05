from fastapi import APIRouter

from app.api.routes import (
    accounts,
    ai,
    analytics,
    auth,
    communities,
    inbox,
    logs,
    posts,
    projects,
    proxies,
    vk_callback,
    vk_oauth,
)

api_router = APIRouter()
for module in (auth, accounts, proxies, projects, communities, posts, inbox, analytics, ai, logs, vk_callback, vk_oauth):
    api_router.include_router(module.router)
