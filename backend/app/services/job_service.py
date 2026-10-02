from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import JobStatus
from app.models.system import Job


def create_job(db: Session, type_: str, *, project_id: int | None = None, params: dict[str, Any] | None = None,
               user_id: int | None = None) -> Job:
    job = Job(type=type_, project_id=project_id, params=params or {}, created_by=user_id,
              status=JobStatus.PENDING.value, result={})
    db.add(job)
    db.flush()
    return job


def finish_job(job: Job, *, result: dict[str, Any] | None = None, error: str | None = None) -> None:
    job.status = JobStatus.FAILED.value if error else JobStatus.SUCCESS.value
    job.result = result or {}
    job.error = error
