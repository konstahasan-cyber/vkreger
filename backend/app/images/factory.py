from __future__ import annotations

from app.images.base import DisabledImageProvider, ImageProvider
from app.services.settings_service import RuntimeSettings

_override: ImageProvider | None = None


def set_image_provider_override(provider: ImageProvider | None) -> None:
    global _override
    _override = provider


def get_image_provider(rs: RuntimeSettings) -> ImageProvider:
    if _override is not None:
        return _override
    name = (rs.IMAGE_PROVIDER or "none").lower()
    if name == "openai":
        from app.images.openai_images import OpenAIImageProvider

        return OpenAIImageProvider(rs.IMAGE_MODEL, rs.IMAGE_QUALITY, rs.image_pricing.get(rs.IMAGE_MODEL, 0.0),
                                   api_key=rs.OPENAI_API_KEY)
    if name == "fake":
        from app.images.fake import FakeImageProvider

        return FakeImageProvider()
    return DisabledImageProvider()
