"""Post generation pipeline.

plan item → COPYWRITER+EDITOR+IMAGE_PROMPT (one request) → local cliché cleanup →
(optional EDITOR pass) → embedding → uniqueness check (regenerate if too similar) →
image generation → draft Post.
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.content.similarity import check_uniqueness, first_line
from app.core.config import settings
from app.core.exceptions import ValidationAppError
from app.images.base import ImageGenerationError
from app.images.factory import get_image_provider
from app.models.content import ContentPlanItem, Post, Rubric
from app.models.enums import ImageFormat, LogLevel, PlanItemStatus, PostStatus
from app.models.project import Project
from app.openai.agents import copywriter, editor
from app.openai.provider import TokenUsage
from app.openai.service import AIService
from app.services.audit import syslog

logger = logging.getLogger(__name__)


def _rubric(db: Session, project_id: int, code: str) -> Rubric | None:
    return db.execute(select(Rubric).where(Rubric.project_id == project_id, Rubric.code == code)).scalar_one_or_none()


def next_plan_item(db: Session, project_id: int) -> ContentPlanItem | None:
    return db.execute(
        select(ContentPlanItem)
        .where(ContentPlanItem.project_id == project_id, ContentPlanItem.status == PlanItemStatus.PLANNED.value)
        .order_by(ContentPlanItem.planned_for.asc().nulls_last(), ContentPlanItem.id)
        .limit(1)
    ).scalar_one_or_none()


def _hashtags_text(text: str, hashtags: list[str]) -> str:
    tags = [h if h.startswith("#") else f"#{h}" for h in (hashtags or []) if h]
    missing = [t for t in tags if t.lower() not in text.lower()]
    if missing:
        text = text.rstrip() + "\n\n" + " ".join(missing)
    return text


def _compose_unique(db: Session, project: Project, ai: AIService, *, rubric_code: str, rubric_desc: str | None,
                    topic: str, angle: str | None, extra_instructions: str | None, automatic: bool, force: bool,
                    exclude_id: int | None = None, avoid: list[str] | None = None):  # noqa: ANN202
    """Compose a post and regenerate while it repeats this group's or a sibling group's posts.

    Returns the least similar attempt: (data, embedding, report, attempts_meta).
    """
    from app.openai.context import sibling_project_ids

    rs = ai.rs
    siblings = sibling_project_ids(db, project)
    avoid = list(avoid or [])
    attempts_meta: list[dict] = []
    best: tuple | None = None
    for attempt in range(settings.MAX_REGENERATIONS + 1):
        data = copywriter.compose_post(
            ai, db, project, rubric_code=rubric_code, rubric_desc=rubric_desc,
            topic=topic, angle=angle, avoid=avoid, automatic=automatic, force=force,
            extra_instructions=extra_instructions,
        )
        text, cliches = editor.local_cleanup(data.get("text", ""))
        if rs.AI_SEPARATE_EDITOR_PASS:
            edited = editor.edit_post(ai, project, text, automatic=automatic)
            text, more = editor.local_cleanup(edited.get("text", text))
            cliches += more
        data["text"] = _hashtags_text(text, data.get("hashtags", []))
        vectors = ai.embed([f"{data.get('title', '')}\n{data.get('topic', '')}\n{data['text'][:1500]}"],
                           project_id=project.id, automatic=automatic)
        embedding = vectors[0] if vectors else None
        report = check_uniqueness(
            db, project.id, title=data.get("title"), topic=data.get("topic") or topic, cta=data.get("cta"),
            embedding=embedding, window=settings.RECENT_POSTS_WINDOW,
            semantic_threshold=float(rs.SIMILARITY_THRESHOLD), title_threshold=float(rs.TITLE_SIMILARITY_THRESHOLD),
            cta_window=settings.CTA_REPEAT_WINDOW, exclude_id=exclude_id, sibling_ids=siblings,
            opening=first_line(data["text"]),
        )
        attempts_meta.append({"attempt": attempt + 1, "ok": report.ok, "reasons": report.reasons,
                              "max_semantic": report.max_semantic, "max_title": report.max_title,
                              "removed_cliches": cliches})
        score = (len(report.reasons), report.max_semantic)
        if best is None or score < best[0]:
            best = (score, data, embedding, report)
        if report.ok:
            break
        avoid = list(dict.fromkeys([*avoid, *report.avoid_hints]))[-8:]
        logger.info("Post for project %s too similar (%s), regenerating", project.id, report.reasons)
    _, data, embedding, report = best
    return data, embedding, report, attempts_meta


def generate_post(
    db: Session,
    project: Project,
    *,
    plan_item: ContentPlanItem | None = None,
    rubric_code: str | None = None,
    topic: str | None = None,
    angle: str | None = None,
    extra_instructions: str | None = None,
    automatic: bool = False,
    force: bool = False,
    with_image: bool | None = None,
    ai: AIService | None = None,
) -> Post:
    ai = ai or AIService(db)
    rs = ai.rs
    if plan_item is None and topic is None:
        plan_item = next_plan_item(db, project.id)
    if plan_item is not None:
        rubric_code = plan_item.rubric_code
        topic = plan_item.topic
        angle = plan_item.angle
    if not topic:
        raise ValidationAppError("Нет темы: составьте контент-план или укажите тему")
    rubric_code = rubric_code or "educational"
    rubric = _rubric(db, project.id, rubric_code)

    data, embedding, report, attempts_meta = _compose_unique(
        db, project, ai, rubric_code=rubric_code, rubric_desc=rubric.description if rubric else None, topic=topic,
        angle=angle, extra_instructions=extra_instructions, automatic=automatic, force=force)

    similarity_warning = bool(report and not report.ok)
    post = Post(
        project_id=project.id,
        community_id=project.community.id if project.community else None,
        title=(data.get("title") or "")[:500],
        text=data.get("text", ""),
        category=rubric_code,
        topic=data.get("topic") or topic,
        cta=data.get("cta"),
        hashtags=data.get("hashtags", []),
        image_prompt=data.get("image_prompt"),
        image_format=project.image_format if project.images_enabled else ImageFormat.NONE.value,
        status=PostStatus.DRAFT.value,
        guid=uuid.uuid4().hex,
        attachments=[],
        analytics={},
        embedding=embedding,
        generation_metadata={
            "operation": "post_compose",
            "model": rs.model_for("post_compose"),
            "plan_item_id": plan_item.id if plan_item else None,
            "angle": angle,
            "editor_notes": data.get("editor_notes", []),
            "uniqueness_attempts": attempts_meta,
            "similarity_warning": similarity_warning,
            "automatic": automatic,
        },
    )
    db.add(post)
    db.flush()
    if plan_item is not None:
        plan_item.status = PlanItemStatus.USED.value
        plan_item.post_id = post.id
    if similarity_warning:
        syslog(db, LogLevel.WARNING, "content",
               f"Post #{post.id} is still similar to previous posts after regenerations", project_id=project.id,
               context={"reasons": report.reasons if report else []})

    use_image = project.images_enabled if with_image is None else with_image
    if use_image and post.image_prompt:
        generate_image_for_post(db, post, ai=ai, automatic=automatic, force=force)
    db.flush()
    return post


def rewrite_post(db: Session, post: Post, *, ai: AIService | None = None, automatic: bool = False,
                 force: bool = False, avoid: list[str] | None = None) -> Post:
    """Rewrite the text of an unpublished post so it no longer repeats other posts (image and time are kept)."""
    if post.status in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value):
        raise ValidationAppError("Опубликованный пост переписать нельзя")
    ai = ai or AIService(db)
    project = db.get(Project, post.project_id)
    rubric = _rubric(db, project.id, post.category or "")
    data, embedding, report, attempts_meta = _compose_unique(
        db, project, ai, rubric_code=post.category or "educational",
        rubric_desc=rubric.description if rubric else None, topic=post.topic or post.title or "",
        angle=(post.generation_metadata or {}).get("angle"),
        extra_instructions="Перепиши по-новому: другой заголовок, другое начало, другая структура и примеры.",
        automatic=automatic, force=force, exclude_id=post.id,
        avoid=[*(avoid or []), post.title or "", f"начало «{first_line(post.text)[:80]}»"])
    post.title = (data.get("title") or post.title or "")[:500]
    post.text = data.get("text", post.text)
    post.topic = data.get("topic") or post.topic
    post.cta = data.get("cta")
    post.hashtags = data.get("hashtags", [])
    post.embedding = embedding
    meta = dict(post.generation_metadata or {})
    meta["rewrites"] = int(meta.get("rewrites", 0)) + 1
    meta["uniqueness_attempts"] = attempts_meta
    meta["similarity_warning"] = bool(report and not report.ok)
    post.generation_metadata = meta
    db.flush()
    return post


def media_path(project_id: int, name: str) -> Path:
    path = Path(settings.MEDIA_ROOT) / str(project_id)
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def generate_image_for_post(db: Session, post: Post, *, ai: AIService | None = None, automatic: bool = False,
                            force: bool = False, fmt: ImageFormat | None = None) -> bool:
    ai = ai or AIService(db)
    provider = get_image_provider(ai.rs)
    if not provider.enabled or not post.image_prompt:
        return False
    fmt = fmt or (ImageFormat(post.image_format) if post.image_format != ImageFormat.NONE.value else ImageFormat.SQUARE)
    ai.guard.check(post.project_id, automatic=automatic, force=force)
    from app.services.brand_service import brand_image_suffix

    project = db.get(Project, post.project_id)
    suffix = brand_image_suffix(project) if project else ""
    prompt = f"{post.image_prompt}. Brand style: {suffix}" if suffix else post.image_prompt
    try:
        image = provider.generate(prompt, fmt)
    except ImageGenerationError as exc:
        syslog(db, LogLevel.WARNING, "images", f"Image for post #{post.id} failed: {exc}", project_id=post.project_id)
        return False
    path = media_path(post.project_id, f"{post.guid}.png")
    path.write_bytes(image.content)
    if post.image_path and post.image_path != str(path) and os.path.exists(post.image_path):
        os.remove(post.image_path)
    post.image_path = str(path)
    post.image_format = fmt.value
    # a new image invalidates a previously uploaded VK photo
    post.attachments = [a for a in (post.attachments or []) if not str(a).startswith("photo")]
    ai.record(model=image.model, operation="image_generate", agent="IMAGE", usage=TokenUsage(),
              project_id=post.project_id, automatic=automatic, images=1, cost=image.cost)
    return True
