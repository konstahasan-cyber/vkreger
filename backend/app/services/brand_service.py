"""Brand style: import from a website, generate avatar/cover, upload them to VK."""
from __future__ import annotations

import io
from typing import Any

from sqlalchemy.orm import Session

from app.content.generator import media_path
from app.core.exceptions import ValidationAppError
from app.db.base import utcnow
from app.images.base import ImageGenerationError
from app.images.factory import get_image_provider
from app.models.enums import ImageFormat, LogLevel
from app.models.project import Project
from app.openai.agents import brand as brand_agent
from app.openai.provider import TokenUsage
from app.openai.service import AIService
from app.services.audit import syslog
from app.vk.errors import VKError, describe_vk_error
from app.vk.factory import client_for_community

COVER_SIZE = (1590, 530)  # VK recommends ~3:1 covers; generated 3:2 image is cropped to this ratio
AVATAR_SIZE = (800, 800)


def _update_brand(project: Project, **values: Any) -> None:
    project.brand = {**(project.brand or {}), **values}


def apply_brand_analysis(db: Session, project: Project, signals: dict[str, Any], *, force: bool = False) -> dict:
    ai = AIService(db)
    style = brand_agent.analyze_brand(ai, project, signals, force=force)
    style["source"] = signals.get("url") or "html-файл"
    style["logo_url"] = signals.get("logo_url")
    style["site_colors"] = signals.get("colors", [])
    style["imported_at"] = utcnow().isoformat()
    _update_brand(project, style=style)
    # fill empty project fields with facts from the site (never overwrite what the user wrote)
    facts = "; ".join(style.get("business_facts") or [])
    if facts and not project.product_description:
        project.product_description = facts[:2000]
    if not project.website and signals.get("url"):
        project.website = signals["url"]
    rules = dict(project.content_rules or {})
    rules["brand_tone"] = style.get("tone_of_voice")
    rules["brand_phrases"] = (style.get("key_phrases") or [])[:8]
    project.content_rules = rules
    db.flush()
    return style


def _crop_to(content: bytes, size: tuple[int, int]) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(content)).convert("RGB")
    target_ratio = size[0] / size[1]
    w, h = image.size
    if w / h > target_ratio:
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        image = image.crop((left, 0, left + new_w, h))
    else:
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        image = image.crop((0, top, w, top + new_h))
    image = image.resize(size)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _design_prompt(project: Project, kind: str) -> str:
    style = (project.brand or {}).get("style") or {}
    design = (project.setup_proposal or {}).get("design") or {}
    base = style.get(f"{kind}_prompt") or design.get(f"{kind}_prompt")
    if not base:
        raise ValidationAppError("Сначала запустите AI-анализ или импортируйте стиль с сайта")
    palette = ", ".join(style.get("palette") or design.get("colors") or [])
    extra = f" Brand palette: {palette}." if palette else ""
    if kind == "avatar":
        extra += " Square social media avatar, single bold centered symbol, clean background, no text, no letters."
    else:
        extra += " Wide social media cover banner, key elements centered, no text, no letters, no logos."
    return base + extra


def generate_design(db: Session, project: Project, kinds: list[str], *, force: bool = False) -> dict:
    ai = AIService(db)
    provider = get_image_provider(ai.rs)
    if not provider.enabled:
        raise ValidationAppError("Генерация картинок выключена (Настройки AI → Генератор картинок)")
    result = {}
    for kind in kinds:
        ai.guard.check(project.id, automatic=False, force=force)
        prompt = _design_prompt(project, kind)
        fmt = ImageFormat.SQUARE if kind == "avatar" else ImageFormat.HORIZONTAL
        try:
            image = provider.generate(prompt, fmt)
        except ImageGenerationError as exc:
            raise ValidationAppError(f"Не удалось сгенерировать {'аватар' if kind == 'avatar' else 'обложку'}: {exc}") from exc
        content = _crop_to(image.content, AVATAR_SIZE if kind == "avatar" else COVER_SIZE)
        path = media_path(project.id, f"{kind}.png")
        path.write_bytes(content)
        ai.record(model=image.model, operation="image_generate", agent="IMAGE", usage=TokenUsage(),
                  project_id=project.id, automatic=False, images=1, cost=image.cost)
        version = int(((project.brand or {}).get(kind) or {}).get("version", 0)) + 1
        _update_brand(project, **{kind: {"path": str(path), "version": version, "prompt": prompt,
                                         "uploaded_version": ((project.brand or {}).get(kind) or {}).get("uploaded_version")}})
        result[kind] = version
    db.flush()
    return result


def upload_design(db: Session, project: Project, kinds: list[str] | None = None) -> dict:
    """Upload generated avatar/cover to the connected VK community."""
    community = project.community
    if community is None:
        raise ValidationAppError("Сначала подключите сообщество")
    brand = project.brand or {}
    kinds = kinds or [k for k in ("avatar", "cover") if brand.get(k)]
    results: dict[str, str] = {}
    for kind in kinds:
        info = brand.get(kind)
        if not info:
            continue
        try:
            content = open(info["path"], "rb").read()
            with client_for_community(community, prefer_community_token=False) as client:
                if kind == "avatar":
                    client.upload_group_avatar(community.vk_group_id, content)
                else:
                    client.upload_cover(community.vk_group_id, content, *COVER_SIZE)
            info = {**info, "uploaded_version": info.get("version")}
            _update_brand(project, **{kind: info})
            brand = project.brand
            results[kind] = "ok"
        except (VKError, OSError, KeyError, TypeError, ValueError) as exc:
            message = describe_vk_error(exc) if isinstance(exc, VKError) else str(exc)
            results[kind] = message
            syslog(db, LogLevel.WARNING, "design", f"Загрузка {kind} в сообщество не удалась: {message}",
                   project_id=project.id)
    db.flush()
    return results


def brand_image_suffix(project: Project) -> str:
    style = (project.brand or {}).get("style") or {}
    return style.get("image_style") or ""
