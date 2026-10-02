"""Image Provider Interface.  Implementations: OpenAI Images, a fake one, or disabled."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.models.enums import ImageFormat


class ImageGenerationError(Exception):
    pass


@dataclass
class GeneratedImage:
    content: bytes
    mime: str
    model: str
    cost: float = 0.0


class ImageProvider(Protocol):
    name: str
    enabled: bool

    def generate(self, prompt: str, fmt: ImageFormat) -> GeneratedImage: ...


class DisabledImageProvider:
    name = "none"
    enabled = False

    def generate(self, prompt: str, fmt: ImageFormat) -> GeneratedImage:
        raise ImageGenerationError("Image generation is disabled")
