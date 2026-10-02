from __future__ import annotations

import base64

from app.images.base import GeneratedImage, ImageGenerationError
from app.models.enums import ImageFormat

# Sizes supported by gpt-image-* models.
SIZES = {
    ImageFormat.SQUARE: "1024x1024",
    ImageFormat.VERTICAL: "1024x1536",
    ImageFormat.HORIZONTAL: "1536x1024",
}


class OpenAIImageProvider:
    name = "openai"
    enabled = True

    def __init__(self, model: str, quality: str, price_per_image: float):
        from app.openai.provider import OpenAIProvider

        self.model = model
        self.quality = quality
        self.price = price_per_image
        self._client = OpenAIProvider().client

    def generate(self, prompt: str, fmt: ImageFormat) -> GeneratedImage:
        import openai

        size = SIZES.get(fmt, SIZES[ImageFormat.SQUARE])
        kwargs = {"model": self.model, "prompt": prompt[:4000], "size": size, "n": 1}
        if self.model.startswith("gpt-image"):
            kwargs["quality"] = self.quality
        else:
            kwargs["response_format"] = "b64_json"
        try:
            response = self._client.images.generate(**kwargs)
        except openai.OpenAIError as exc:
            raise ImageGenerationError(f"OpenAI image generation failed: {type(exc).__name__}: {exc}") from exc
        b64 = response.data[0].b64_json if response.data else None
        if not b64:
            raise ImageGenerationError("OpenAI returned no image data")
        return GeneratedImage(content=base64.b64decode(b64), mime="image/png", model=self.model, cost=self.price)
