"""LLM provider interface.  The rest of the application depends only on ``LLMProvider``;
switching models is a config change and switching vendors means adding one class."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.core.config import settings

logger = logging.getLogger(__name__)


class AIError(Exception):
    pass


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0


@dataclass
class LLMResult:
    data: dict[str, Any]
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMProvider(Protocol):
    name: str

    def complete_json(
        self,
        *,
        model: str,
        instructions: str,
        input_text: str,
        schema: dict[str, Any],
        schema_name: str,
        max_output_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult: ...

    def embed(self, *, model: str, texts: list[str]) -> EmbeddingResult: ...


def _is_reasoning_model(model: str) -> bool:
    return model.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4"))


class OpenAIProvider:
    """OpenAI Responses API with Structured Outputs (``text.format = json_schema``)."""

    name = "openai"

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        from openai import OpenAI

        key = api_key or settings.OPENAI_API_KEY
        if not key:
            raise AIError("OPENAI_API_KEY is not configured")
        self._client = OpenAI(api_key=key, base_url=base_url or settings.OPENAI_BASE_URL,
                              timeout=settings.OPENAI_TIMEOUT, max_retries=2)

    @property
    def client(self):  # noqa: ANN201 - used by the image provider
        return self._client

    def complete_json(self, *, model: str, instructions: str, input_text: str, schema: dict[str, Any],
                      schema_name: str, max_output_tokens: int, cache_key: str | None = None) -> LLMResult:
        import openai

        kwargs: dict[str, Any] = {
            "model": model,
            "instructions": instructions,
            "input": input_text,
            "max_output_tokens": max_output_tokens,
            "store": False,
            "text": {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": True}},
        }
        if cache_key:
            kwargs["prompt_cache_key"] = cache_key
        if _is_reasoning_model(model):
            kwargs["reasoning"] = {"effort": "low"}
        try:
            response = self._client.responses.create(**kwargs)
        except openai.OpenAIError as exc:
            raise AIError(f"OpenAI request failed: {type(exc).__name__}: {exc}") from exc
        usage = TokenUsage()
        if response.usage:
            usage.input_tokens = response.usage.input_tokens or 0
            usage.output_tokens = response.usage.output_tokens or 0
            details = getattr(response.usage, "input_tokens_details", None)
            usage.cached_tokens = getattr(details, "cached_tokens", 0) or 0
        if getattr(response, "status", "completed") == "incomplete":
            reason = getattr(getattr(response, "incomplete_details", None), "reason", "unknown")
            raise AIError(f"OpenAI response incomplete: {reason}")
        text = response.output_text
        try:
            data = json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise AIError("Model returned invalid JSON (refusal?)") from exc
        return LLMResult(data=data, model=model, usage=usage)

    def embed(self, *, model: str, texts: list[str]) -> EmbeddingResult:
        import openai

        try:
            response = self._client.embeddings.create(model=model, input=texts)
        except openai.OpenAIError as exc:
            raise AIError(f"OpenAI embeddings failed: {type(exc).__name__}") from exc
        vectors = [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        return EmbeddingResult(vectors=vectors, model=model,
                               usage=TokenUsage(input_tokens=response.usage.prompt_tokens or 0))


_provider_override: LLMProvider | None = None


def set_provider_override(provider: LLMProvider | None) -> None:
    global _provider_override
    _provider_override = provider


def get_provider(rs=None) -> LLMProvider:  # noqa: ANN001 - rs: RuntimeSettings (key entered in the panel)
    if _provider_override is not None:
        return _provider_override
    if settings.AI_PROVIDER == "fake":
        from app.openai.fake import FakeProvider

        return FakeProvider()
    return OpenAIProvider(api_key=getattr(rs, "OPENAI_API_KEY", None) if rs is not None else None)


def verify_openai_key(key: str) -> str | None:
    """Return None if the key works, otherwise a human-readable error."""
    import openai
    from openai import OpenAI

    try:
        OpenAI(api_key=key, base_url=settings.OPENAI_BASE_URL, timeout=20, max_retries=1).models.list()
    except openai.AuthenticationError:
        return "OpenAI не принял ключ (неверный или отозванный)"
    except openai.PermissionDeniedError:
        return "Ключ верный, но у него нет доступа (проверьте права ключа или проекта в OpenAI)"
    except openai.OpenAIError as exc:
        return f"Не удалось проверить ключ: {type(exc).__name__}"
    return None
