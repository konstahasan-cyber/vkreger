"""Application configuration loaded from environment variables (.env).

Everything that may differ between deployments lives here: secrets, AI models,
pricing, limits and scheduling knobs.  A subset of AI-related settings can be
overridden at runtime from the admin panel (see ``app.services.settings_service``).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# USD per 1M tokens.  Defaults only — override with AI_PRICING_JSON or in AI Settings.
DEFAULT_PRICING: dict[str, dict[str, float]] = {
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.5},
    "gpt-5.4-nano": {"input": 0.2, "cached_input": 0.02, "output": 1.25},
    "gpt-5.4": {"input": 2.5, "cached_input": 0.25, "output": 15.0},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-4.1-mini": {"input": 0.4, "cached_input": 0.1, "output": 1.6},
    "gpt-4.1": {"input": 2.0, "cached_input": 0.5, "output": 8.0},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.6},
    "text-embedding-3-small": {"input": 0.02, "cached_input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "cached_input": 0.13, "output": 0.0},
}
# USD per generated image (approximate, medium quality).
DEFAULT_IMAGE_PRICING: dict[str, float] = {
    "gpt-image-1": 0.042,
    "gpt-image-1-mini": 0.011,
    "gpt-image-1.5": 0.04,
    "gpt-image-2": 0.04,
    "dall-e-3": 0.04,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- general ---
    APP_NAME: str = "VKreger"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api"
    # comma-separated list or JSON array
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    PUBLIC_BASE_URL: str = "http://localhost:8000"  # used for VK Callback API server URL
    MEDIA_ROOT: str = "/data/media"

    # --- security ---
    SECRET_KEY: str = "change-me"
    # Comma-separated Fernet keys; the first one encrypts, all of them decrypt (rotation).
    ENCRYPTION_KEYS: str = ""
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    ADMIN_EMAIL: str | None = None
    ADMIN_PASSWORD: str | None = None

    # --- infrastructure ---
    DATABASE_URL: str = "postgresql+psycopg2://vk:vk@localhost:5432/vkreger"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # --- VK ---
    VK_API_VERSION: str = "5.199"
    VK_API_BASE_URL: str = "https://api.vk.com/method"
    VK_REQUEST_TIMEOUT: float = 30.0
    VK_MIN_REQUEST_INTERVAL: float = 0.34  # VK allows ~3 req/s per user token

    # --- proxy ---
    PROXY_CHECK_URL: str = "http://ip-api.com/json/?fields=status,message,country,countryCode,query"
    PROXY_CHECK_TIMEOUT: float = 10.0
    PROXY_DEAD_AFTER_FAILS: int = 2
    PROXY_DEFAULT_HTTP_PORT: int = 8080
    PROXY_DEFAULT_SOCKS_PORT: int = 1080

    # --- OpenAI ---
    OPENAI_API_KEY: str | None = None
    OPENAI_BASE_URL: str | None = None
    OPENAI_TIMEOUT: float = 120.0
    AI_PROVIDER: str = "openai"  # openai | fake (tests / offline demo)
    AI_DEFAULT_MODEL: str = "gpt-5.4-mini"
    # Per-operation model overrides, e.g. {"project_setup": "gpt-5.4", "inbox_triage": "gpt-5.4-nano"}
    AI_MODEL_OVERRIDES: dict[str, str] = Field(default_factory=dict)
    AI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    AI_EMBEDDINGS_ENABLED: bool = True
    AI_SEPARATE_EDITOR_PASS: bool = False
    AI_PRICING_JSON: dict[str, dict[str, float]] = Field(default_factory=dict)
    AI_MAX_OUTPUT_TOKENS: int = 4000

    # --- images ---
    IMAGE_PROVIDER: str = "openai"  # openai | none | fake
    IMAGE_MODEL: str = "gpt-image-1"
    IMAGE_QUALITY: str = "medium"
    IMAGE_PRICING_JSON: dict[str, float] = Field(default_factory=dict)

    # --- cost limits (USD) ---
    MAX_AI_COST_PER_DAY: float = 10.0
    MAX_AI_COST_PER_PROJECT_DAY: float = 2.0

    # --- content ---
    SIMILARITY_THRESHOLD: float = 0.88  # cosine similarity of embeddings
    TITLE_SIMILARITY_THRESHOLD: float = 0.75  # lexical similarity of titles
    CTA_REPEAT_WINDOW: int = 3  # the same CTA may not appear in the last N posts
    RECENT_POSTS_WINDOW: int = 30
    MAX_REGENERATIONS: int = 2
    QUEUE_HORIZON_DAYS: int = 3

    # --- publishing ---
    PUBLISH_MAX_ATTEMPTS: int = 4
    PUBLISH_RETRY_BASE_SECONDS: int = 60
    PUBLISH_STUCK_MINUTES: int = 10

    # --- analytics ---
    ANALYTICS_COLLECT_DAYS: int = 14
    ANALYST_MIN_INTERVAL_DAYS: int = 7
    ANALYST_MIN_NEW_POSTS: int = 10

    # --- inbox ---
    OPERATOR_WEBHOOK_URL: str | None = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            if v.strip().startswith("["):
                import json

                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def pricing(self) -> dict[str, dict[str, float]]:
        return {**DEFAULT_PRICING, **self.AI_PRICING_JSON}

    @property
    def image_pricing(self) -> dict[str, float]:
        return {**DEFAULT_IMAGE_PRICING, **self.IMAGE_PRICING_JSON}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
