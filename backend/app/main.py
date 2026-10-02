from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ANN201
    from app.services.user_service import bootstrap_admin

    with SessionLocal() as db:
        try:
            bootstrap_admin(db)
        except Exception as exc:  # noqa: BLE001 — DB may not be migrated yet
            logger.warning("Admin bootstrap skipped: %s", type(exc).__name__)
    yield


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    if settings.ENVIRONMENT == "production" and settings.SECRET_KEY == "change-me":
        raise RuntimeError("SECRET_KEY must be set in production")
    app = FastAPI(title=f"{settings.APP_NAME} API", version="1.0.0", lifespan=lifespan,
                  openapi_url=f"{settings.API_PREFIX}/openapi.json", docs_url=f"{settings.API_PREFIX}/docs")
    app.add_middleware(CORSMiddleware, allow_origins=settings.CORS_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @app.get(f"{settings.API_PREFIX}/health")
    def health() -> dict:
        status = {"status": "ok", "db": "ok"}
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            status.update(status="degraded", db="error")
        return status

    app.include_router(api_router, prefix=settings.API_PREFIX)
    media = Path(settings.MEDIA_ROOT)
    media.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=media), name="media")
    return app


app = create_app()
