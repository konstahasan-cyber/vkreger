"""Changing a community's topic and editing published posts in VK."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission, has_permission
from app.db.session import get_db
from app.models.content import Post
from app.models.enums import PostStatus
from app.models.user import User
from app.schemas.common import JobOut
from app.schemas.post import PostOut
from app.services import project_service, retheme_service
from app.services.audit import audit
from app.services.job_service import create_job

router = APIRouter(tags=["retheme"])


class RethemeBrief(BaseModel):
    business_name: str | None = Field(default=None, max_length=255)
    theme: str | None = Field(default=None, max_length=255)
    niche: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=255)
    target_audience: str | None = None
    product_description: str | None = None
    advantages: str | None = None
    website: str | None = Field(default=None, max_length=512)
    contacts: str | None = None


class RethemeRequest(BaseModel):
    brief: RethemeBrief
    scope: Literal["published", "all"] = "all"
    force: bool = False


class ApplyRequest(BaseModel):
    keep_image: bool = True
    post_ids: list[int] | None = None


class ProposalUpdate(BaseModel):
    text: str | None = None
    title: str | None = None
    include: bool | None = None


class EditInVK(BaseModel):
    text: str = Field(min_length=1)
    title: str | None = None
    keep_image: bool = True


def _post(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Пост не найден")
    return post


@router.post("/projects/{project_id}/retheme", response_model=JobOut, status_code=202)
def start(project_id: int, body: RethemeRequest, request: Request, db: Session = Depends(get_db),
          user: User = Depends(require(Permission.MANAGE_CONTENT))) -> JobOut:
    from app.workers.tasks.ai_jobs import retheme_prepare_task

    if body.force and not has_permission(user.role, Permission.FORCE_AI_LIMIT):
        raise HTTPException(403, "Превысить лимит расходов на AI может только администратор")
    project = project_service.get_project(db, project_id)
    brief = body.brief.model_dump(exclude_none=True)
    if not any(str(v).strip() for v in brief.values()):
        raise HTTPException(422, "Опишите новую тематику")
    retheme_service.discard(db, project)
    job = create_job(db, "retheme_prepare", project_id=project.id, user_id=user.id,
                     params={"brief": brief, "scope": body.scope, "force": body.force})
    audit(db, user.id, "project.retheme", "project", project.id, {"scope": body.scope, "fields": sorted(brief)},
          client_ip(request))
    db.commit()
    retheme_prepare_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/projects/{project_id}/retheme")
def list_proposals(project_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    project = project_service.get_project(db, project_id)
    items = []
    for post in retheme_service.proposals(db, project):
        proposal = post.generation_metadata["retheme"]
        items.append({
            "post_id": post.id, "status": post.status, "published": post.status == PostStatus.PUBLISHED.value,
            "published_at": post.published_at, "scheduled_at": post.scheduled_at, "category": post.category,
            "vk_post_id": post.vk_post_id, "has_image": bool(post.image_path) or any(
                str(a).startswith("photo") for a in post.attachments or []),
            "old_title": post.title, "old_text": post.text if proposal["status"] != "applied" else
            ((post.generation_metadata.get("history") or [{}])[-1].get("text") or ""),
            "new_title": proposal.get("title"), "new_text": proposal.get("text"),
            "include": proposal.get("include", True), "retheme_status": proposal["status"],
            "error": proposal.get("error"), "edited": proposal.get("edited", False),
        })
    counts = {s: sum(1 for i in items if i["retheme_status"] == s) for s in ("proposed", "applied", "failed")}
    return {"items": items, "counts": counts}


@router.patch("/posts/{post_id}/retheme")
def update_proposal(post_id: int, body: ProposalUpdate, db: Session = Depends(get_db),
                    _: User = Depends(require(Permission.MANAGE_CONTENT))) -> dict:
    proposal = retheme_service.update_proposal(db, _post(db, post_id), text=body.text, title=body.title,
                                               include=body.include)
    db.commit()
    return proposal


@router.post("/projects/{project_id}/retheme/apply", response_model=JobOut, status_code=202)
def apply(project_id: int, body: ApplyRequest, request: Request, db: Session = Depends(get_db),
          user: User = Depends(require(Permission.PUBLISH))) -> JobOut:
    from app.workers.tasks.ai_jobs import retheme_apply_task

    project = project_service.get_project(db, project_id)
    job = create_job(db, "retheme_apply", project_id=project.id, user_id=user.id, params=body.model_dump())
    audit(db, user.id, "project.retheme_apply", "project", project.id, body.model_dump(), client_ip(request))
    db.commit()
    retheme_apply_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.delete("/projects/{project_id}/retheme")
def discard(project_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.MANAGE_CONTENT))) -> dict:
    count = retheme_service.discard(db, project_service.get_project(db, project_id))
    db.commit()
    return {"discarded": count}


@router.post("/posts/{post_id}/edit-vk", response_model=PostOut)
def edit_in_vk(post_id: int, body: EditInVK, request: Request, db: Session = Depends(get_db),
               user: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    """Change the text of an already published post right in VK (date, likes and comments stay)."""
    from app.vk.errors import VKError, describe_vk_error

    post = _post(db, post_id)
    try:
        retheme_service.edit_in_vk(db, post, body.text, title=body.title, keep_image=body.keep_image)
    except VKError as exc:
        db.rollback()
        raise HTTPException(502, f"VK не дал изменить пост: {describe_vk_error(exc)}") from exc
    audit(db, user.id, "post.edit_in_vk", "post", post.id, {"keep_image": body.keep_image}, client_ip(request))
    db.commit()
    return PostOut.from_model(post)
