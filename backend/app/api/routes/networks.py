"""Networks: bulk connection of many groups on one topic and network-wide uniqueness."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.exceptions import AppError
from app.core.rbac import Permission, has_permission
from app.db.session import get_db
from app.models.content import Post
from app.models.enums import ProjectGoal, Tone
from app.models.user import User
from app.schemas.common import JobOut
from app.services import network_service, project_service
from app.services.audit import audit
from app.services.job_service import create_job
from app.services.settings_service import load_runtime_settings
from app.vk.errors import VKError, describe_vk_error

router = APIRouter(prefix="/networks", tags=["networks"])


class Brief(BaseModel):
    business_name: str = Field(min_length=1, max_length=255)
    theme: str | None = None
    niche: str | None = None
    city: str | None = None
    target_audience: str | None = None
    product_description: str | None = None
    advantages: str | None = None
    website: str | None = None
    contacts: str | None = None
    goal: ProjectGoal = ProjectGoal.LEADS
    tone: Tone = Tone.FRIENDLY
    timezone: str = "Europe/Moscow"


class LaunchOptions(BaseModel):
    days: int = Field(default=14, ge=1, le=60)
    cadence_days: int = Field(default=1, ge=1, le=14)
    post_times: list[str] = Field(default_factory=lambda: ["10:00"], min_length=1, max_length=4)
    start_date: date | None = None
    with_image: bool = False
    auto_schedule: bool = False
    force: bool = False

    @field_validator("post_times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        from app.schemas.project import ProjectBase

        return ProjectBase._times(value)


class ParseRequest(BaseModel):
    lines: str


class BulkRequest(LaunchOptions):
    network: str = Field(min_length=1, max_length=255)
    brief: Brief
    lines: str
    generate: bool = True


class NetworkRequest(LaunchOptions):
    network: str = Field(min_length=1, max_length=255)


class AddProjectsRequest(BaseModel):
    network: str = Field(min_length=1, max_length=255)
    project_ids: list[int] = Field(min_length=1)


def _check_force(user: User, force: bool) -> None:
    if force and not has_permission(user.role, Permission.FORCE_AI_LIMIT):
        raise HTTPException(403, "Превысить лимит расходов на AI может только администратор")


def _launch(db: Session, user: User, network: str, project_ids: list[int], options: LaunchOptions) -> JobOut:
    from app.workers.tasks.ai_jobs import network_launch_task

    params = options.model_dump(mode="json", include=set(LaunchOptions.model_fields))
    job = create_job(db, "network_launch", params={**params, "network": network, "project_ids": project_ids},
                     user_id=user.id)
    db.commit()
    network_launch_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("")
def list_networks(db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    return network_service.list_networks(db)


@router.get("/detail")
def network_detail(name: str, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    return network_service.network_overview(db, name)


@router.post("/parse")
def parse(body: ParseRequest, _: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    """Preview: what was recognised in the pasted lines (keys are masked)."""
    items = network_service.parse_lines(body.lines)
    return {"items": [i.to_dict() for i in items], "valid": sum(1 for i in items if not i.error)}


@router.post("/bulk")
def bulk(body: BulkRequest, request: Request, db: Session = Depends(get_db),
         user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    """Connect many groups at once (one line — one group with its community key) and start generation."""
    _check_force(user, body.force)
    items = network_service.parse_lines(body.lines)
    if not any(not i.error for i in items):
        raise HTTPException(422, "Не найдено ни одной строки с ключом доступа")
    brief = body.brief.model_dump(mode="json")
    brief.update({"posting_times": body.post_times, "images_enabled": body.with_image,
                  "posts_per_week": max(1, round(7 * len(body.post_times) / body.cadence_days))})
    results, project_ids = [], []
    for item in items:
        row = {"line": item.line, "group": item.group, "label": item.label}
        if item.error:
            results.append({**row, "ok": False, "error": item.error})
            continue
        savepoint = db.begin_nested()
        try:
            project, created = network_service.connect_group(db, item, brief, body.network.strip())
            savepoint.commit()
        except VKError as exc:
            savepoint.rollback()
            results.append({**row, "ok": False, "error": describe_vk_error(exc)})
            continue
        except AppError as exc:
            savepoint.rollback()
            results.append({**row, "ok": False, "error": exc.message})
            continue
        project_ids.append(project.id)
        results.append({**row, "ok": True, "project_id": project.id, "name": project.name, "created": created,
                        "persona": (project.brand or {}).get("persona", {}).get("name")})
    audit(db, user.id, "network.bulk_connect", "network", None,
          {"network": body.network, "connected": len(project_ids), "lines": len(items)}, client_ip(request))
    db.commit()
    job = _launch(db, user, body.network.strip(), project_ids, body) if body.generate and project_ids else None
    return {"results": results, "connected": len(project_ids), "job": job}


@router.post("/projects")
def add_projects(body: AddProjectsRequest, request: Request, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    """Put existing projects into a network: they get different voices and a shared repeat check."""
    added = []
    for project_id in body.project_ids:
        project = project_service.get_project(db, project_id)
        network_service.add_to_network(db, project, body.network)
        added.append({"project_id": project.id, "persona": project.brand["persona"]["name"]})
    audit(db, user.id, "network.add_projects", "network", None, {"network": body.network, "projects": body.project_ids},
          client_ip(request))
    db.commit()
    return {"added": added}


@router.post("/generate", response_model=JobOut, status_code=202)
def generate(body: NetworkRequest, db: Session = Depends(get_db),
             user: User = Depends(require(Permission.MANAGE_CONTENT))) -> JobOut:
    """Write posts for every group of the network for the chosen period."""
    _check_force(user, body.force)
    projects = [p for p in network_service.network_projects(db, body.network) if p.community]
    if not projects:
        raise HTTPException(422, "В сети нет групп с подключённым сообществом")
    return _launch(db, user, body.network, [p.id for p in projects], body)


@router.get("/similar")
def similar(name: str, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> dict:
    rs = load_runtime_settings(db)
    pairs = network_service.similar_pairs(db, name, semantic_threshold=float(rs.SIMILARITY_THRESHOLD),
                                          title_threshold=float(rs.TITLE_SIMILARITY_THRESHOLD))
    return {"pairs": pairs, "to_rewrite": len({p["rewrite"]["id"] for p in pairs if p["can_rewrite"]})}


class DedupeRequest(BaseModel):
    network: str
    force: bool = False


@router.post("/dedupe", response_model=JobOut, status_code=202)
def dedupe(body: DedupeRequest, db: Session = Depends(get_db),
           user: User = Depends(require(Permission.MANAGE_CONTENT))) -> JobOut:
    from app.workers.tasks.ai_jobs import network_dedupe_task

    _check_force(user, body.force)
    job = create_job(db, "network_dedupe", params={"network": body.network, "force": body.force}, user_id=user.id)
    db.commit()
    network_dedupe_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/rewrite/{post_id}")
def rewrite(post_id: int, db: Session = Depends(get_db), user: User = Depends(require(Permission.MANAGE_CONTENT))) -> dict:
    """Rewrite one post so it stops repeating others (text only; image and time stay)."""
    from app.content.generator import rewrite_post

    post = db.get(Post, post_id)
    if post is None:
        raise HTTPException(404, "Пост не найден")
    rewrite_post(db, post)
    db.commit()
    return {"id": post.id, "title": post.title, "similarity_warning": post.generation_metadata.get("similarity_warning")}
