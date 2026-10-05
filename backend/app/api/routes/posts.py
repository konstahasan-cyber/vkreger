from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission, has_permission
from app.db.session import get_db
from app.models.content import Post
from app.models.enums import PostStatus
from app.models.user import User
from app.schemas.common import JobOut, Page
from app.schemas.post import GeneratePostsRequest, ImageRequest, PostCreate, PostOut, PostUpdate, ScheduleRequest
from app.services import project_service
from app.services.audit import audit
from app.services.job_service import create_job
from app.services.publishing_service import publish_post_now, schedule_post

router = APIRouter(tags=["content"])


def _get(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Пост не найден")
    return post


@router.get("/posts", response_model=Page[PostOut])
def list_posts(project_id: int | None = None, status: str | None = None, category: str | None = None,
               date_from: datetime | None = None, date_to: datetime | None = None, limit: int = 50, offset: int = 0,
               db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> Page[PostOut]:
    query = select(Post)
    if project_id:
        query = query.where(Post.project_id == project_id)
    if status:
        query = query.where(Post.status.in_(status.split(",")))
    if category:
        query = query.where(Post.category == category)
    if date_from:
        query = query.where(func.coalesce(Post.published_at, Post.scheduled_at, Post.created_at) >= date_from)
    if date_to:
        query = query.where(func.coalesce(Post.published_at, Post.scheduled_at, Post.created_at) < date_to)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(func.coalesce(Post.scheduled_at, Post.created_at).desc(), Post.id.desc())
                      .limit(min(limit, 200)).offset(offset)).scalars()
    return Page(items=[PostOut.from_model(p) for p in rows], total=total)


@router.get("/posts/export")
def export_posts(project_id: int | None = None, status: str | None = None, fmt: str = "csv",
                 db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> Response:
    """Download posts in the order they went out (published, then planned): Excel-friendly CSV or plain text."""
    import csv
    import io
    from zoneinfo import ZoneInfo

    from app.models.project import Project

    when = func.coalesce(Post.published_at, Post.scheduled_at, Post.created_at)
    query = select(Post)
    if project_id:
        query = query.where(Post.project_id == project_id)
    if status:
        query = query.where(Post.status.in_(status.split(",")))
    posts = list(db.execute(query.order_by(when.asc(), Post.id)).scalars())
    projects = {p.id: p for p in db.execute(select(Project)).scalars()}
    labels = {"draft": "На проверке", "approved": "Одобрен", "scheduled": "В очереди", "publishing": "Публикуется",
              "published": "Опубликован", "failed": "Ошибка"}

    def local(post: Post) -> str:
        value = post.published_at or post.scheduled_at
        if not value:
            return ""
        project = projects.get(post.project_id)
        try:
            zone = ZoneInfo(project.timezone if project else "Europe/Moscow")
        except Exception:  # noqa: BLE001
            zone = ZoneInfo("UTC")
        return value.astimezone(zone).strftime("%d.%m.%Y %H:%M")

    def link(post: Post) -> str:
        if post.vk_post_id and post.community:
            return f"https://vk.com/wall-{post.community.vk_group_id}_{post.vk_post_id}"
        return ""

    stamp = datetime.now(UTC).strftime("%Y%m%d")
    if fmt == "txt":
        blocks = []
        for i, post in enumerate(posts, 1):
            head = f"#{i} · {local(post) or 'без даты'} · {labels.get(post.status, post.status)} · {post.category or '-'}"
            parts = [head, link(post), "", post.text.strip()]
            blocks.append("\n".join(p for p in parts if p is not None))
        body = ("\n\n" + "—" * 40 + "\n\n").join(blocks) + "\n"
        return Response(body.encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="posts-{stamp}.txt"'})
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")  # ';' + BOM opens correctly in Russian Excel
    writer.writerow(["№", "Дата", "Статус", "Проект", "Рубрика", "Заголовок", "Текст", "Ссылка VK", "Просмотры",
                     "Лайки", "Комментарии", "Репосты"])
    for i, post in enumerate(posts, 1):
        a = post.analytics or {}
        project = projects.get(post.project_id)
        writer.writerow([i, local(post), labels.get(post.status, post.status), project.name if project else "",
                         post.category or "", post.title or "", post.text, link(post), a.get("views", ""),
                         a.get("likes", ""), a.get("comments", ""), a.get("reposts", "")])
    return Response(("\ufeff" + out.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="posts-{stamp}.csv"'})


@router.get("/calendar")
def calendar(date_from: datetime, date_to: datetime, project_id: int | None = None, db: Session = Depends(get_db),
             _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    when = func.coalesce(Post.published_at, Post.scheduled_at)
    query = select(Post).where(when >= date_from, when < date_to)
    if project_id:
        query = query.where(Post.project_id == project_id)
    return [{"id": p.id, "project_id": p.project_id, "title": p.title or (p.text[:60] if p.text else ""),
             "category": p.category, "status": p.status, "at": p.published_at or p.scheduled_at}
            for p in db.execute(query.order_by(when)).scalars()]


@router.get("/posts/{post_id}", response_model=PostOut)
def get_post(post_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> PostOut:
    return PostOut.from_model(_get(db, post_id))


@router.post("/posts", response_model=PostOut, status_code=201)
def create_post(body: PostCreate, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.MANAGE_CONTENT))) -> PostOut:
    project = project_service.get_project(db, body.project_id)
    post = Post(project_id=project.id, community_id=project.community.id if project.community else None,
                title=body.title, text=body.text, category=body.category, topic=body.title,
                attachments=body.attachments, hashtags=[], analytics={}, guid=uuid.uuid4().hex,
                generation_metadata={"manual": True, "author_id": user.id}, status=PostStatus.DRAFT.value)
    db.add(post)
    db.flush()
    if body.scheduled_at:
        schedule_post(db, post, body.scheduled_at)
    audit(db, user.id, "post.create", "post", post.id, {"project_id": project.id}, client_ip(request))
    db.commit()
    return PostOut.from_model(post)


@router.patch("/posts/{post_id}", response_model=PostOut)
def update_post(post_id: int, body: PostUpdate, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.MANAGE_CONTENT))) -> PostOut:
    post = _get(db, post_id)
    if post.status in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value):
        raise HTTPException(409, "Опубликованный пост нельзя редактировать")
    changes = body.model_dump(exclude_unset=True)
    if "image_format" in changes and changes["image_format"] is not None:
        changes["image_format"] = changes["image_format"].value
    for key, value in changes.items():
        setattr(post, key, value)
    meta = dict(post.generation_metadata or {})
    meta["edited_by"] = user.id
    post.generation_metadata = meta
    db.commit()
    return PostOut.from_model(post)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(post_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.MANAGE_CONTENT))) -> None:
    post = _get(db, post_id)
    if post.status == PostStatus.PUBLISHING.value:
        raise HTTPException(409, "Пост сейчас публикуется")
    audit(db, user.id, "post.delete", "post", post.id, {"status": post.status}, client_ip(request))
    db.delete(post)
    db.commit()


@router.post("/posts/generate", response_model=JobOut, status_code=202)
def generate(body: GeneratePostsRequest, db: Session = Depends(get_db),
             user: User = Depends(require(Permission.MANAGE_CONTENT))) -> JobOut:
    from app.workers.tasks.ai_jobs import generate_posts_task

    if body.force and not has_permission(user.role, Permission.FORCE_AI_LIMIT):
        raise HTTPException(403, "Превысить лимит расходов на AI может только администратор")
    project_service.get_project(db, body.project_id)
    job = create_job(db, "generate_posts", project_id=body.project_id, params=body.model_dump(mode="json", exclude={"project_id"}),
                     user_id=user.id)
    db.commit()
    generate_posts_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


class ApproveAllRequest(BaseModel):
    project_id: int | None = None


@router.post("/posts/approve-all")
def approve_all(body: ApproveAllRequest, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.PUBLISH))) -> dict:
    """Approve every draft: keep its planned time if it is in the future, else take the next free slot."""
    from app.core.exceptions import AppError

    query = select(Post).where(Post.status == PostStatus.DRAFT.value)
    if body.project_id:
        query = query.where(Post.project_id == body.project_id)
    drafts = list(db.execute(query.order_by(Post.scheduled_at.asc().nulls_last(), Post.id)).scalars())
    now = datetime.now(UTC)
    approved, errors = 0, []
    for post in drafts:
        try:
            keep = post.scheduled_at if post.scheduled_at and post.scheduled_at > now else None
            if keep is None:
                post.scheduled_at = None  # free its stale slot before picking a new one
                db.flush()
            schedule_post(db, post, keep)
            approved += 1
        except AppError as exc:
            errors.append(f"#{post.id}: {exc.message}")
    audit(db, user.id, "post.approve_all", "post", None, {"approved": approved, "project_id": body.project_id},
          client_ip(request))
    db.commit()
    return {"approved": approved, "errors": errors}


@router.post("/posts/{post_id}/duplicate", response_model=PostOut, status_code=201)
def duplicate(post_id: int, request: Request, db: Session = Depends(get_db),
              user: User = Depends(require(Permission.MANAGE_CONTENT))) -> PostOut:
    """Create an identical draft (text, title, category, image) that can be scheduled separately."""
    import shutil
    from pathlib import Path

    original = _get(db, post_id)
    copy = Post(
        project_id=original.project_id, community_id=original.community_id, title=original.title, text=original.text,
        category=original.category, topic=original.topic, cta=original.cta, hashtags=list(original.hashtags or []),
        # uploaded VK photos are re-uploaded for the copy; other attachments (links, etc.) are kept
        attachments=[a for a in original.attachments or [] if not str(a).startswith("photo")],
        image_prompt=original.image_prompt, image_format=original.image_format, status=PostStatus.DRAFT.value,
        guid=uuid.uuid4().hex, analytics={}, is_pinned=False,
        generation_metadata={"copied_from": original.id, "copied_by": user.id},
    )
    if original.image_path and Path(original.image_path).exists():
        target = Path(original.image_path).with_name(f"{copy.guid}.png")
        shutil.copyfile(original.image_path, target)
        copy.image_path = str(target)
    db.add(copy)
    db.flush()
    audit(db, user.id, "post.duplicate", "post", copy.id, {"from": original.id}, client_ip(request))
    db.commit()
    return PostOut.from_model(copy)


@router.post("/posts/{post_id}/approve", response_model=PostOut)
def approve(post_id: int, request: Request, db: Session = Depends(get_db),
            user: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    """Approve a draft: scheduled if it has a time (or gets the next free slot)."""
    post = _get(db, post_id)
    if post.status not in (PostStatus.DRAFT.value, PostStatus.APPROVED.value, PostStatus.FAILED.value):
        raise HTTPException(409, f"Действие недоступно для поста в статусе «{post.status}»")
    if post.community_id is None:
        post.status = PostStatus.APPROVED.value
    else:
        schedule_post(db, post, post.scheduled_at if post.scheduled_at and post.scheduled_at > datetime.now(post.scheduled_at.tzinfo) else None)
    audit(db, user.id, "post.approve", "post", post.id, ip=client_ip(request))
    db.commit()
    return PostOut.from_model(post)


@router.post("/posts/{post_id}/schedule", response_model=PostOut)
def schedule(post_id: int, body: ScheduleRequest, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    post = _get(db, post_id)
    schedule_post(db, post, body.scheduled_at)
    audit(db, user.id, "post.schedule", "post", post.id, {"at": post.scheduled_at.isoformat()}, client_ip(request))
    db.commit()
    return PostOut.from_model(post)


@router.post("/posts/{post_id}/unschedule", response_model=PostOut)
def unschedule(post_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    post = _get(db, post_id)
    if post.status != PostStatus.SCHEDULED.value:
        raise HTTPException(409, f"Действие недоступно для поста в статусе «{post.status}»")
    post.status = PostStatus.DRAFT.value
    db.commit()
    return PostOut.from_model(post)


@router.post("/posts/{post_id}/publish-now", response_model=PostOut)
def publish_now(post_id: int, request: Request, db: Session = Depends(get_db),
                user: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    post = _get(db, post_id)
    publish_post_now(db, post)
    audit(db, user.id, "post.publish_now", "post", post.id, {"result": post.status}, client_ip(request))
    db.commit()
    return PostOut.from_model(post)


@router.post("/posts/{post_id}/retry", response_model=PostOut)
def retry(post_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.PUBLISH))) -> PostOut:
    post = _get(db, post_id)
    if post.status != PostStatus.FAILED.value:
        raise HTTPException(409, "Повторить можно только пост с ошибкой")
    post.attempts = 0
    schedule_post(db, post, datetime.now().astimezone())
    db.commit()
    return PostOut.from_model(post)


@router.post("/posts/{post_id}/image", response_model=PostOut)
def regenerate_image(post_id: int, body: ImageRequest, db: Session = Depends(get_db),
                     user: User = Depends(require(Permission.MANAGE_CONTENT))) -> PostOut:
    from app.content.generator import generate_image_for_post

    if body.force and not has_permission(user.role, Permission.FORCE_AI_LIMIT):
        raise HTTPException(403, "Превысить лимит расходов на AI может только администратор")
    post = _get(db, post_id)
    if post.status in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value):
        raise HTTPException(409, f"Действие недоступно для поста в статусе «{post.status}»")
    if body.image_prompt:
        post.image_prompt = body.image_prompt
    if not generate_image_for_post(db, post, fmt=body.image_format, force=body.force):
        db.commit()
        raise HTTPException(409, "Генерация картинок выключена или не удалась (подробности — в Журнале)")
    db.commit()
    return PostOut.from_model(post)


@router.delete("/posts/{post_id}/image", response_model=PostOut)
def remove_image(post_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.MANAGE_CONTENT))) -> PostOut:
    post = _get(db, post_id)
    post.image_path = None
    post.image_format = "none"
    post.attachments = [a for a in post.attachments or [] if not str(a).startswith("photo")]
    db.commit()
    return PostOut.from_model(post)
