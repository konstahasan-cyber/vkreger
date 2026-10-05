from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require
from app.core.rbac import Permission, has_permission
from app.db.session import get_db
from app.models.content import ContentPlanItem, Rubric, Strategy
from app.models.enums import PlanItemStatus, ProjectStatus
from app.models.project import Project
from app.models.user import User
from app.models.vk_account import VKAccount
from app.schemas.common import JobOut
from app.schemas.community import CommunityOut
from app.schemas.project import (
    CommunityConnectRequest,
    CommunityCreateRequest,
    CommunityPreview,
    ContentPlanRequest,
    PlanItemOut,
    PlanItemUpdate,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectUpdate,
    RubricCreate,
    RubricOut,
    RubricUpdate,
    SetupRequest,
)
from app.services import community_service, project_service
from app.services.audit import audit
from app.services.job_service import create_job
from app.vk.errors import VKAPIError, VKError, describe_vk_error

router = APIRouter(prefix="/projects", tags=["projects"])


def _enum_value(value):  # noqa: ANN001, ANN202
    return value.value if hasattr(value, "value") else value


def _check_force(user: User, force: bool) -> None:
    if force and not has_permission(user.role, Permission.FORCE_AI_LIMIT):
        raise HTTPException(403, "Превысить лимит расходов на AI может только администратор")


def _detail(db: Session, project: Project) -> ProjectDetail:
    base = ProjectOut.from_model(project).model_dump()
    strategy = project_service.active_strategy(db, project.id)
    return ProjectDetail(
        **base,
        setup_proposal=project.setup_proposal or {},
        rubrics=[RubricOut.model_validate(r) for r in sorted(project.rubrics, key=lambda r: r.id)],
        strategy=strategy.data if strategy else None,
        strategy_version=strategy.version if strategy else None,
    )


def _validate_account(db: Session, account_id: int | None) -> None:
    if account_id is not None and db.get(VKAccount, account_id) is None:
        raise HTTPException(422, "Аккаунт VK не найден")


@router.get("", response_model=list[ProjectOut])
def list_projects(status: str | None = None, db: Session = Depends(get_db),
                  _: User = Depends(require(Permission.VIEW))) -> list[ProjectOut]:
    query = select(Project).order_by(Project.id.desc())
    if status:
        query = query.where(Project.status == status)
    else:
        query = query.where(Project.status != ProjectStatus.ARCHIVED.value)
    return [ProjectOut.from_model(p) for p in db.execute(query).scalars()]


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(body: ProjectCreate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> ProjectDetail:
    _validate_account(db, body.vk_account_id)
    data = {k: _enum_value(v) for k, v in body.model_dump().items()}
    data["auto_reply_types"] = [_enum_value(v) for v in body.auto_reply_types]
    project = Project(**data, setup_proposal={}, brand={}, content_rules={}, status=ProjectStatus.DRAFT.value)
    db.add(project)
    db.flush()
    audit(db, user.id, "project.create", "project", project.id, {"name": project.name}, client_ip(request))
    db.commit()
    return _detail(db, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> ProjectDetail:
    return _detail(db, project_service.get_project(db, project_id))


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: int, body: ProjectUpdate, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> ProjectDetail:
    project = project_service.get_project(db, project_id)
    changes = body.model_dump(exclude_unset=True)
    if "vk_account_id" in changes:
        _validate_account(db, changes["vk_account_id"])
    if "status" in changes:
        ProjectStatus(changes["status"])
    for key, value in changes.items():
        if key == "auto_reply_types" and value is not None:
            value = [_enum_value(v) for v in value]
        setattr(project, key, _enum_value(value))
    audit(db, user.id, "project.update", "project", project.id, {"fields": sorted(changes)}, client_ip(request))
    db.commit()
    return _detail(db, project)


@router.delete("/{project_id}", status_code=204)
def archive_project(project_id: int, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> None:
    project = project_service.get_project(db, project_id)
    project.status = ProjectStatus.ARCHIVED.value
    project.autopilot = False
    audit(db, user.id, "project.archive", "project", project.id, ip=client_ip(request))
    db.commit()


# ------------------------------------------------------------------ AI setup / wizard
@router.post("/{project_id}/setup", response_model=JobOut, status_code=202)
def run_setup(project_id: int, body: SetupRequest, db: Session = Depends(get_db),
              user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> JobOut:
    from app.workers.tasks.ai_jobs import project_setup_task

    _check_force(user, body.force)
    project = project_service.get_project(db, project_id)
    job = create_job(db, "project_setup", project_id=project.id, params={"force": body.force}, user_id=user.id)
    db.commit()
    project_setup_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/{project_id}/preview", response_model=CommunityPreview)
def preview(project_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> CommunityPreview:
    project = project_service.get_project(db, project_id)
    data = project.setup_proposal or {}
    if not data:
        raise HTTPException(409, "Сначала запустите AI-анализ")
    community = data.get("community", {})
    return CommunityPreview(
        name_options=community.get("name_options", []),
        description=community.get("description", ""),
        status=community.get("status", ""),
        design=data.get("design", {}),
        rubrics=data.get("rubrics", []),
        strategy=data.get("strategy", {}),
        pinned_post=data.get("pinned_post", {}),
        analysis=data.get("analysis", {}),
    )


def _launch(db: Session, project: Project, user: User, params: dict) -> JobOut:
    from app.workers.tasks.ai_jobs import launch_community_task

    job = create_job(db, "launch_community", project_id=project.id, params=params, user_id=user.id)
    db.commit()
    launch_community_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{project_id}/community/create")
def create_community(project_id: int, body: CommunityCreateRequest, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    _check_force(user, body.force)
    project = project_service.get_project(db, project_id)
    try:
        community = community_service.create_community(db, project, title=body.title, description=body.description,
                                                       public_category=body.public_category, subtype=body.subtype)
    except VKAPIError as exc:
        db.rollback()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    except VKError as exc:
        db.rollback()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    audit(db, user.id, "community.create", "community", community.id,
          {"project_id": project.id, "vk_group_id": community.vk_group_id, "title": body.title}, client_ip(request))
    db.commit()
    job = _launch(db, project, user, {"description": body.description, "status": body.status,
                                      "pinned_post": body.pinned_post, "first_queue": body.first_queue,
                                      "queue_size": body.queue_size, "force": body.force})
    return {"community": CommunityOut.from_model(community).model_dump(mode="json"), "job": job.model_dump(mode="json")}


@router.post("/{project_id}/community/connect")
def connect_community(project_id: int, body: CommunityConnectRequest, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    _check_force(user, body.force)
    project = project_service.get_project(db, project_id)
    try:
        community = community_service.connect_community(db, project, body.vk_group_id, body.community_token)
    except VKAPIError as exc:
        db.rollback()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    except VKError as exc:
        db.rollback()
        raise HTTPException(502, describe_vk_error(exc)) from exc
    audit(db, user.id, "community.connect", "community", community.id,
          {"project_id": project.id, "vk_group_id": community.vk_group_id}, client_ip(request))
    db.commit()
    job = None
    if body.apply_settings or body.pinned_post or body.first_queue:
        job = _launch(db, project, user, {
            "description": body.description if body.apply_settings else None,
            "status": body.status if body.apply_settings else None,
            "pinned_post": body.pinned_post, "first_queue": body.first_queue, "queue_size": body.queue_size,
            "force": body.force,
        }).model_dump(mode="json")
    else:
        community_service.activate_project(db, project)
        db.commit()
    return {"community": CommunityOut.from_model(community).model_dump(mode="json"), "job": job}


@router.post("/{project_id}/community/disconnect", status_code=204)
def disconnect_community(project_id: int, request: Request, db: Session = Depends(get_db),
                         user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> None:
    project = project_service.get_project(db, project_id)
    if project.community:
        audit(db, user.id, "community.disconnect", "community", project.community.id, {"project_id": project.id},
              client_ip(request))
        project.community.project_id = None
    db.commit()


# ------------------------------------------------------------------ strategy / plan / rubrics
@router.get("/{project_id}/strategies")
def strategies(project_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> list[dict]:
    rows = db.execute(select(Strategy).where(Strategy.project_id == project_id).order_by(Strategy.version.desc())).scalars()
    return [{"id": s.id, "version": s.version, "is_active": s.is_active, "source": s.source, "data": s.data,
             "reasoning": s.reasoning, "created_at": s.created_at} for s in rows]


@router.post("/{project_id}/content-plan", response_model=JobOut, status_code=202)
def content_plan(project_id: int, body: ContentPlanRequest, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_CONTENT))) -> JobOut:
    from app.workers.tasks.ai_jobs import content_plan_task

    _check_force(user, body.force)
    project = project_service.get_project(db, project_id)
    job = create_job(db, "content_plan", project_id=project.id, params=body.model_dump(), user_id=user.id)
    db.commit()
    content_plan_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.get("/{project_id}/plan", response_model=list[PlanItemOut])
def plan_items(project_id: int, status: str | None = None, db: Session = Depends(get_db),
               _: User = Depends(require(Permission.VIEW))) -> list[ContentPlanItem]:
    query = select(ContentPlanItem).where(ContentPlanItem.project_id == project_id)
    if status:
        query = query.where(ContentPlanItem.status == status)
    return list(db.execute(query.order_by(ContentPlanItem.planned_for.asc().nulls_last(), ContentPlanItem.id)).scalars())


@router.patch("/{project_id}/plan/{item_id}", response_model=PlanItemOut)
def update_plan_item(project_id: int, item_id: int, body: PlanItemUpdate, db: Session = Depends(get_db),
                     _: User = Depends(require(Permission.MANAGE_CONTENT))) -> ContentPlanItem:
    item = db.get(ContentPlanItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(404, "Тема не найдена")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes:
        PlanItemStatus(changes["status"])
    for key, value in changes.items():
        setattr(item, key, value)
    db.commit()
    return item


@router.delete("/{project_id}/plan/{item_id}", status_code=204)
def delete_plan_item(project_id: int, item_id: int, db: Session = Depends(get_db),
                     _: User = Depends(require(Permission.MANAGE_CONTENT))) -> None:
    item = db.get(ContentPlanItem, item_id)
    if item is None or item.project_id != project_id:
        raise HTTPException(404, "Тема не найдена")
    db.delete(item)
    db.commit()


@router.post("/{project_id}/rubrics", response_model=RubricOut, status_code=201)
def add_rubric(project_id: int, body: RubricCreate, db: Session = Depends(get_db),
               _: User = Depends(require(Permission.MANAGE_CONTENT))) -> Rubric:
    project = project_service.get_project(db, project_id)
    project_service.apply_rubrics(db, project, [body.model_dump()])
    db.commit()
    return next(r for r in project.rubrics if r.code == project_service._slug(body.code))


@router.patch("/{project_id}/rubrics/{rubric_id}", response_model=RubricOut)
def update_rubric(project_id: int, rubric_id: int, body: RubricUpdate, db: Session = Depends(get_db),
                  _: User = Depends(require(Permission.MANAGE_CONTENT))) -> Rubric:
    rubric = db.get(Rubric, rubric_id)
    if rubric is None or rubric.project_id != project_id:
        raise HTTPException(404, "Рубрика не найдена")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(rubric, key, value)
    db.commit()
    return rubric


@router.post("/{project_id}/fill-queue", response_model=JobOut, status_code=202)
def fill_queue(project_id: int, db: Session = Depends(get_db),
               user: User = Depends(require(Permission.MANAGE_CONTENT)), max_new: int = 5, force: bool = False) -> JobOut:
    from app.workers.tasks.ai_jobs import fill_queue_job

    _check_force(user, force)
    project = project_service.get_project(db, project_id)
    job = create_job(db, "fill_queue", project_id=project.id, params={"max_new": max_new, "force": force},
                     user_id=user.id)
    db.commit()
    fill_queue_job.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{project_id}/analyst-review", response_model=JobOut, status_code=202)
def analyst_review(project_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> JobOut:
    from app.workers.tasks.ai_jobs import analyst_review_job

    project = project_service.get_project(db, project_id)
    job = create_job(db, "analyst_review", project_id=project.id, user_id=user.id)
    db.commit()
    analyst_review_job.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


# ------------------------------------------------------------------ brand style & design
class BrandImportRequest(BaseModel):
    url: str = Field(min_length=4, max_length=500)
    force: bool = False


class DesignRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["avatar", "cover"])
    upload: bool = True
    force: bool = False


@router.post("/{project_id}/brand/import", response_model=JobOut, status_code=202)
def brand_import(project_id: int, body: BrandImportRequest, db: Session = Depends(get_db),
                 user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> JobOut:
    from app.workers.tasks.ai_jobs import brand_import_task

    _check_force(user, body.force)
    project = project_service.get_project(db, project_id)
    job = create_job(db, "brand_import", project_id=project.id, params={"url": body.url.strip(), "force": body.force},
                     user_id=user.id)
    db.commit()
    brand_import_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{project_id}/brand/upload", response_model=JobOut, status_code=202)
async def brand_upload(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                       user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> JobOut:
    from app.content.brand_import import BrandImportError, signals_from_upload
    from app.workers.tasks.ai_jobs import brand_import_task

    project = project_service.get_project(db, project_id)
    content = await file.read(2_000_001)
    try:
        signals = signals_from_upload(content).to_dict()
    except BrandImportError as exc:
        raise HTTPException(422, str(exc)) from exc
    job = create_job(db, "brand_import", project_id=project.id, params={"signals": signals, "file": file.filename},
                     user_id=user.id)
    db.commit()
    brand_import_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{project_id}/design/generate", response_model=JobOut, status_code=202)
def design_generate(project_id: int, body: DesignRequest, db: Session = Depends(get_db),
                    user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> JobOut:
    from app.workers.tasks.ai_jobs import design_generate_task

    _check_force(user, body.force)
    kinds = [k for k in body.kinds if k in ("avatar", "cover")]
    if not kinds:
        raise HTTPException(422, "Укажите avatar и/или cover")
    project = project_service.get_project(db, project_id)
    job = create_job(db, "design_generate", project_id=project.id,
                     params={"kinds": kinds, "upload": body.upload, "force": body.force}, user_id=user.id)
    db.commit()
    design_generate_task.delay(job.id)
    db.refresh(job)
    return JobOut.model_validate(job)


@router.post("/{project_id}/design/upload")
def design_upload(project_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require(Permission.MANAGE_PROJECTS))) -> dict:
    from app.services.brand_service import upload_design

    project = project_service.get_project(db, project_id)
    result = upload_design(db, project)
    db.commit()
    return result
