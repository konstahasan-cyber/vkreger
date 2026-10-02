from __future__ import annotations

import struct
import zlib

from app.images.base import GeneratedImage
from app.models.enums import ImageFormat

_DIMS = {ImageFormat.SQUARE: (64, 64), ImageFormat.VERTICAL: (64, 96), ImageFormat.HORIZONTAL: (96, 64)}


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    row = b"\x00" + bytes(rgb) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class FakeImageProvider:
    """Generates a solid-colour PNG — for tests and offline demos."""

    name = "fake"
    enabled = True

    def generate(self, prompt: str, fmt: ImageFormat) -> GeneratedImage:
        h = abs(hash(prompt))
        w, hgt = _DIMS.get(fmt, (64, 64))
        return GeneratedImage(content=_png(w, hgt, (h % 256, (h >> 8) % 256, (h >> 16) % 256)), mime="image/png",
                              model="fake", cost=0.0)
