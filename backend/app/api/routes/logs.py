from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require
from app.core.rbac import Permission
from app.db.session import get_db
from app.models.system import AuditLog, Job, SystemLog
from app.models.user import User
from app.schemas.common import JobOut, Page
from app.schemas.logs import AuditLogOut, SystemLogOut

router = APIRouter(tags=["logs"])


@router.get("/logs/system", response_model=Page[SystemLogOut])
def system_logs(level: str | None = None, source: str | None = None, project_id: int | None = None,
                q: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db),
                _: User = Depends(require(Permission.VIEW_LOGS))) -> Page[SystemLogOut]:
    query = select(SystemLog)
    if level:
        query = query.where(SystemLog.level.in_(level.split(",")))
    if source:
        query = query.where(SystemLog.source == source)
    if project_id:
        query = query.where(SystemLog.project_id == project_id)
    if q:
        query = query.where(SystemLog.message.ilike(f"%{q}%"))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(SystemLog.id.desc()).limit(min(limit, 500)).offset(offset)).scalars()
    return Page(items=[SystemLogOut.model_validate(r) for r in rows], total=total)


@router.get("/logs/audit", response_model=Page[AuditLogOut])
def audit_logs(action: str | None = None, limit: int = 100, offset: int = 0, db: Session = Depends(get_db),
               _: User = Depends(require(Permission.VIEW_LOGS))) -> Page[AuditLogOut]:
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
    rows = db.execute(query.order_by(AuditLog.id.desc()).limit(min(limit, 500)).offset(offset)).scalars()
    return Page(items=[AuditLogOut.model_validate(r) for r in rows], total=total)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, db: Session = Depends(get_db), _: User = Depends(require(Permission.VIEW))) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(project_id: int | None = None, limit: int = 30, db: Session = Depends(get_db),
              _: User = Depends(require(Permission.VIEW))) -> list[Job]:
    query = select(Job)
    if project_id:
        query = query.where(Job.project_id == project_id)
    return list(db.execute(query.order_by(Job.id.desc()).limit(min(limit, 200))).scalars())
