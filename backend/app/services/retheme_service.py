"""Changing a community's topic: rewrite its posts (published ones too) for the new business.

Two steps so nothing goes to VK unseen:
1. ``prepare`` — the project gets the new brief and a new AI strategy, every post gets a proposed
   new text (stored in ``generation_metadata["retheme"]``);
2. ``apply`` — proposals the user kept are written: published posts through ``wall.edit``
   (same post: date, likes and comments stay), the others just locally.
The previous text of every changed post is kept in ``generation_metadata["history"]``.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import CostLimitExceeded, ValidationAppError
from app.models.content import ContentPlanItem, Post, Rubric
from app.models.enums import LogLevel, PlanItemStatus, PostStatus
from app.models.project import Project
from app.openai.agents import copywriter
from app.openai.provider import AIError
from app.openai.service import AIService
from app.services import project_service
from app.services.audit import syslog
from app.vk.errors import VKAPIError, VKError, describe_vk_error
from app.vk.factory import run_for_community

logger = logging.getLogger(__name__)

BRIEF_FIELDS = ("business_name", "theme", "niche", "city", "target_audience", "product_description", "advantages",
                "website", "contacts")
EDITABLE = (PostStatus.DRAFT.value, PostStatus.APPROVED.value, PostStatus.SCHEDULED.value, PostStatus.FAILED.value)
STOP_CODES = {9, 14}  # flood control / captcha: stop, never retry around them


def _meta(post: Post) -> dict:
    return dict(post.generation_metadata or {})


def _set_meta(post: Post, **values) -> None:  # noqa: ANN003
    meta = _meta(post)
    meta.update(values)
    post.generation_metadata = meta


def _retheme(post: Post) -> dict | None:
    value = (post.generation_metadata or {}).get("retheme")
    return dict(value) if isinstance(value, dict) else None


def scope_posts(db: Session, project: Project, scope: str) -> list[Post]:
    statuses = [PostStatus.PUBLISHED.value] + (list(EDITABLE) if scope == "all" else [])
    query = select(Post).where(Post.project_id == project.id, Post.status.in_(statuses), Post.is_pinned.is_(False))
    posts = list(db.execute(query).scalars())
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(posts, key=lambda p: (p.published_at or p.scheduled_at or p.created_at or epoch, p.id))


def apply_brief(db: Session, project: Project, brief: dict, *, force: bool = False, ai: AIService | None = None) -> None:
    """New business data → new AI analysis, rubrics and strategy; old plan topics are dropped."""
    previous = {f: getattr(project, f) for f in BRIEF_FIELDS}
    changed = False
    for field in BRIEF_FIELDS:
        value = (brief.get(field) or "").strip() if isinstance(brief.get(field), str) else brief.get(field)
        if value and value != getattr(project, field):
            setattr(project, field, value)
            changed = True
    if not changed:
        raise ValidationAppError("Опишите новую тематику: хотя бы название бизнеса или что вы предлагаете")
    brand = dict(project.brand or {})
    brand.pop("style", None)  # the old website style belongs to the old business
    brand["previous_briefs"] = [*(brand.get("previous_briefs") or [])[-4:],
                                {**previous, "changed_at": datetime.now(UTC).isoformat()}]
    project.brand = brand
    status = project.status
    data = project_service.run_setup(db, project, force=force, ai=ai)
    project.status = status  # setup marks a project «proposal ready»; a running project stays as it was
    new_codes = {project_service._slug(r.get("code", "")) for r in data.get("rubrics", [])}
    if new_codes:
        db.execute(update(Rubric).where(Rubric.project_id == project.id, Rubric.code.not_in(new_codes))
                   .values(is_active=False))
    db.execute(update(ContentPlanItem).where(ContentPlanItem.project_id == project.id,
                                             ContentPlanItem.status == PlanItemStatus.PLANNED.value)
               .values(status=PlanItemStatus.SKIPPED.value))
    db.flush()


def propose(db: Session, project: Project, post: Post, already: list[str], *, force: bool = False,
            ai: AIService | None = None) -> dict:
    ai = ai or AIService(db)
    data = copywriter.retheme_post(ai, db, project, old_text=post.text, rubric_code=post.category,
                                   already_written=already, force=force)
    proposal = {
        "status": "proposed", "include": True, "title": (data.get("title") or "")[:500],
        "text": data.get("text") or "", "topic": data.get("topic"), "cta": data.get("cta"),
        "hashtags": data.get("hashtags") or [], "image_prompt": data.get("image_prompt"),
        "prepared_at": datetime.now(UTC).isoformat(),
    }
    tags = [h if h.startswith("#") else f"#{h}" for h in proposal["hashtags"] if h]
    missing = [t for t in tags if t.lower() not in proposal["text"].lower()]
    if missing:
        proposal["text"] = proposal["text"].rstrip() + "\n\n" + " ".join(missing)
    _set_meta(post, retheme=proposal)
    db.flush()
    return proposal


def prepare(db: Session, project: Project, brief: dict, scope: str, *, force: bool = False,
            progress=None) -> dict:  # noqa: ANN001
    ai = AIService(db)
    apply_brief(db, project, brief, force=force, ai=ai)
    db.commit()
    posts = scope_posts(db, project, scope)
    done, errors, already = 0, [], []
    for post in posts:
        try:
            proposal = propose(db, project, post, already, force=force, ai=ai)
            already.append(proposal["title"])
            done += 1
            db.commit()
        except CostLimitExceeded as exc:
            db.rollback()
            errors.append(exc.message)
            break
        except AIError as exc:
            db.rollback()
            errors.append(f"#{post.id}: {exc}")
        if progress:
            progress(done, len(posts))
    return {"prepared": done, "total": len(posts), "errors": errors}


def proposals(db: Session, project: Project) -> list[Post]:
    posts = db.execute(select(Post).where(Post.project_id == project.id)).scalars()
    found = [p for p in posts if _retheme(p) and _retheme(p).get("status") in ("proposed", "failed", "applied")]
    epoch = datetime.min.replace(tzinfo=UTC)
    return sorted(found, key=lambda p: (p.published_at or p.scheduled_at or p.created_at or epoch, p.id))


def _attachments(post: Post, keep_image: bool) -> list[str]:
    items = [str(a) for a in post.attachments or []]
    return items if keep_image else [a for a in items if not a.startswith("photo")]


def _remember(post: Post) -> None:
    meta = _meta(post)
    history = list(meta.get("history") or [])
    history.append({"title": post.title, "text": post.text, "at": datetime.now(UTC).isoformat()})
    meta["history"] = history[-5:]
    post.generation_metadata = meta


def edit_in_vk(db: Session, post: Post, text: str, *, title: str | None = None, keep_image: bool = True) -> Post:
    """Change the text of a published post in VK (wall.edit) and in the panel."""
    text = (text or "").strip()
    if not text:
        raise ValidationAppError("Текст поста пустой")
    if post.status != PostStatus.PUBLISHED.value or not post.vk_post_id:
        raise ValidationAppError("Пост ещё не опубликован — его можно просто отредактировать")
    community = post.community
    if community is None:
        raise ValidationAppError("У поста нет сообщества")
    attachments = _attachments(post, keep_image)
    run_for_community(community, lambda client: client.wall_edit(community.vk_group_id, int(post.vk_post_id), text,
                                                                 attachments=attachments))
    _remember(post)
    post.text = text
    if title is not None:
        post.title = title[:500]
    post.attachments = attachments
    post.embedding = None
    _set_meta(post, edited_in_vk_at=datetime.now(UTC).isoformat())
    db.flush()
    return post


def _apply_local(post: Post, proposal: dict, keep_image: bool) -> None:
    _remember(post)
    post.text = proposal["text"]
    post.title = proposal.get("title") or post.title
    if not keep_image:
        post.attachments = _attachments(post, False)
        post.image_path = None
        post.image_format = "none"
        post.image_prompt = proposal.get("image_prompt") or post.image_prompt


def apply(db: Session, project: Project, *, keep_image: bool = True, post_ids: list[int] | None = None,
          progress=None) -> dict:  # noqa: ANN001
    targets = [p for p in proposals(db, project)
               if _retheme(p)["status"] in ("proposed", "failed") and _retheme(p).get("include", True)
               and (post_ids is None or p.id in post_ids)]
    applied, failed, stopped = 0, [], None
    for index, post in enumerate(targets):
        proposal = _retheme(post)
        if stopped:
            break
        try:
            if post.status == PostStatus.PUBLISHED.value and post.vk_post_id:
                edit_in_vk(db, post, proposal["text"], title=proposal.get("title"), keep_image=keep_image)
            elif post.status in EDITABLE:
                _apply_local(post, proposal, keep_image)
            else:
                raise ValidationAppError(f"пост в статусе «{post.status}» сейчас нельзя менять")
            post.topic = proposal.get("topic") or post.topic
            post.cta = proposal.get("cta") or post.cta
            post.hashtags = proposal.get("hashtags") or post.hashtags
            post.embedding = None
            _set_meta(post, retheme={**proposal, "status": "applied", "error": None,
                                     "applied_at": datetime.now(UTC).isoformat()})
            applied += 1
        except VKError as exc:
            message = describe_vk_error(exc)
            _set_meta(post, retheme={**proposal, "status": "failed", "error": message})
            failed.append({"post": post.id, "error": message})
            if isinstance(exc, VKAPIError) and exc.code in STOP_CODES:
                stopped = message
        except ValidationAppError as exc:
            _set_meta(post, retheme={**proposal, "status": "failed", "error": exc.message})
            failed.append({"post": post.id, "error": exc.message})
        db.commit()
        if progress:
            progress(index + 1, len(targets))
    if failed:
        syslog(db, LogLevel.WARNING, "retheme", f"Project #{project.id}: {len(failed)} posts were not changed",
               project_id=project.id, context={"failed": failed[:20]})
        db.commit()
    return {"applied": applied, "failed": failed, "stopped": stopped, "total": len(targets)}


def discard(db: Session, project: Project) -> int:
    count = 0
    for post in proposals(db, project):
        if _retheme(post)["status"] != "applied":
            meta = _meta(post)
            meta.pop("retheme", None)
            post.generation_metadata = meta
            count += 1
    db.flush()
    return count


def update_proposal(db: Session, post: Post, *, text: str | None = None, title: str | None = None,
                    include: bool | None = None) -> dict:
    proposal = _retheme(post)
    if not proposal or proposal["status"] == "applied":
        raise ValidationAppError("Для этого поста нет нового текста")
    if text is not None:
        if not text.strip():
            raise ValidationAppError("Текст пустой")
        proposal["text"] = text.strip()
        proposal["edited"] = True
    if title is not None:
        proposal["title"] = title[:500]
    if include is not None:
        proposal["include"] = include
    _set_meta(post, retheme=proposal)
    db.flush()
    return proposal
