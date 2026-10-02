"""AI Service — the single entry point for every LLM call.

Responsibilities: choose the model for an operation (config, not code), enforce cost
limits, call the provider, record token usage and estimated cost.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.system import AIUsage
from app.openai.pricing import estimate_cost
from app.openai.provider import AIError, LLMProvider, TokenUsage, get_provider
from app.openai.usage import CostGuard
from app.services.settings_service import RuntimeSettings, load_runtime_settings

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self, db: Session, provider: LLMProvider | None = None, rs: RuntimeSettings | None = None):
        self.db = db
        self.rs = rs or load_runtime_settings(db)
        self._provider = provider
        self.guard = CostGuard(db, self.rs)

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = get_provider()
        return self._provider

    def record(self, *, model: str, operation: str, agent: str | None, usage: TokenUsage, project_id: int | None,
               automatic: bool, success: bool = True, images: int = 0, cost: float | None = None) -> AIUsage:
        if cost is None:
            cost = estimate_cost(model, usage.input_tokens, usage.output_tokens, usage.cached_tokens, self.rs.pricing)
        row = AIUsage(model=model, operation=operation, agent=agent, input_tokens=usage.input_tokens,
                      output_tokens=usage.output_tokens, cached_tokens=usage.cached_tokens, images=images,
                      estimated_cost=cost, project_id=project_id, success=success, automatic=automatic)
        self.db.add(row)
        self.db.flush()
        return row

    def run(
        self,
        *,
        operation: str,
        agent: str,
        instructions: str,
        input_text: str,
        schema: dict[str, Any],
        project_id: int | None,
        automatic: bool = False,
        force: bool = False,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        self.guard.check(project_id, automatic=automatic, force=force)
        model = self.rs.model_for(operation)
        try:
            result = self.provider.complete_json(
                model=model,
                instructions=instructions,
                input_text=input_text,
                schema=schema,
                schema_name=operation,
                max_output_tokens=max_output_tokens or settings.AI_MAX_OUTPUT_TOKENS,
                cache_key=f"vkreger:{operation}:{project_id or 0}",
            )
        except AIError:
            self.record(model=model, operation=operation, agent=agent, usage=TokenUsage(), project_id=project_id,
                        automatic=automatic, success=False)
            raise
        usage_row = self.record(model=result.model, operation=operation, agent=agent, usage=result.usage,
                                project_id=project_id, automatic=automatic)
        logger.info("AI %s/%s model=%s in=%s out=%s cost=$%.5f", agent, operation, result.model,
                    result.usage.input_tokens, result.usage.output_tokens, usage_row.estimated_cost)
        return result.data

    def embed(self, texts: list[str], *, project_id: int | None, automatic: bool = False) -> list[list[float]] | None:
        if not self.rs.AI_EMBEDDINGS_ENABLED or not texts:
            return None
        model = self.rs.AI_EMBEDDING_MODEL
        try:
            result = self.provider.embed(model=model, texts=texts)
        except AIError as exc:
            logger.warning("Embeddings unavailable: %s", exc)
            return None
        self.record(model=model, operation="embedding", agent="EDITOR", usage=result.usage, project_id=project_id,
                    automatic=automatic)
        return result.vectors
