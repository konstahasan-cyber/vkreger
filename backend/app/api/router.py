from fastapi import APIRouter

from app.api.routes import (
    accounts,
    ai,
    analytics,
    auth,
    communities,
    inbox,
    logs,
    networks,
    posts,
    projects,
    proxies,
    retheme,
    vk_callback,
    vk_oauth,
)

api_router = APIRouter()
for module in (auth, accounts, proxies, projects, communities, posts, retheme, networks, inbox, analytics, ai, logs, vk_callback, vk_oauth):
    api_router.include_router(module.router)
