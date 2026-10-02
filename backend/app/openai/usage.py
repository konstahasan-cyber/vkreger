"""AI usage accounting and cost limits."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import CostLimitExceeded
from app.models.system import AIUsage
from app.services.settings_service import RuntimeSettings


def start_of_today() -> datetime:
    now = datetime.now(UTC)
    return datetime.combine(now.date(), time.min, tzinfo=UTC)


def spent_since(db: Session, since: datetime, project_id: int | None = None) -> float:
    query = select(func.coalesce(func.sum(AIUsage.estimated_cost), 0.0)).where(AIUsage.created_at >= since)
    if project_id is not None:
        query = query.where(AIUsage.project_id == project_id)
    return float(db.execute(query).scalar_one())


class CostGuard:
    """Blocks AI calls once daily limits are exceeded.

    Automatic tasks are always stopped.  Manual operations are stopped too unless the
    caller explicitly forces them (requires the FORCE_AI_LIMIT permission).
    """

    def __init__(self, db: Session, rs: RuntimeSettings):
        self.db = db
        self.rs = rs

    def status(self, project_id: int | None = None) -> dict:
        today = start_of_today()
        total = spent_since(self.db, today)
        result = {
            "spent_today": round(total, 4),
            "limit_day": float(self.rs.MAX_AI_COST_PER_DAY),
            "global_exceeded": total >= float(self.rs.MAX_AI_COST_PER_DAY),
        }
        if project_id is not None:
            project_total = spent_since(self.db, today, project_id)
            result.update({
                "project_spent_today": round(project_total, 4),
                "limit_project_day": float(self.rs.MAX_AI_COST_PER_PROJECT_DAY),
                "project_exceeded": project_total >= float(self.rs.MAX_AI_COST_PER_PROJECT_DAY),
            })
        return result

    def check(self, project_id: int | None, *, automatic: bool, force: bool = False) -> None:
        status = self.status(project_id)
        exceeded = status["global_exceeded"] or status.get("project_exceeded", False)
        if not exceeded:
            return
        if force and not automatic:
            return
        scope = "global" if status["global_exceeded"] else f"project #{project_id}"
        raise CostLimitExceeded(f"Daily AI cost limit exceeded ({scope}); automatic AI tasks are paused")


def usage_report(db: Session) -> dict:
    now = datetime.now(UTC)
    today = start_of_today()
    report = {
        "today": spent_since(db, today),
        "last_7_days": spent_since(db, now - timedelta(days=7)),
        "last_30_days": spent_since(db, now - timedelta(days=30)),
    }
    since = now - timedelta(days=30)
    by_project = db.execute(
        select(AIUsage.project_id, func.sum(AIUsage.estimated_cost), func.count())
        .where(AIUsage.created_at >= since).group_by(AIUsage.project_id)
    ).all()
    by_operation = db.execute(
        select(AIUsage.operation, func.sum(AIUsage.estimated_cost), func.count(),
               func.sum(AIUsage.input_tokens), func.sum(AIUsage.output_tokens))
        .where(AIUsage.created_at >= since).group_by(AIUsage.operation)
    ).all()
    by_model = db.execute(
        select(AIUsage.model, func.sum(AIUsage.estimated_cost), func.count())
        .where(AIUsage.created_at >= since).group_by(AIUsage.model)
    ).all()
    day = func.date(AIUsage.created_at)
    daily = db.execute(
        select(day, func.sum(AIUsage.estimated_cost)).where(AIUsage.created_at >= since).group_by(day).order_by(day)
    ).all()
    report["by_project"] = [{"project_id": p, "cost": round(float(c or 0), 4), "calls": n} for p, c, n in by_project]
    report["by_operation"] = [
        {"operation": o, "cost": round(float(c or 0), 4), "calls": n, "input_tokens": int(i or 0),
         "output_tokens": int(out or 0)} for o, c, n, i, out in by_operation
    ]
    report["by_model"] = [{"model": m, "cost": round(float(c or 0), 4), "calls": n} for m, c, n in by_model]
    report["daily"] = [{"date": str(d), "cost": round(float(c or 0), 4)} for d, c in daily]
    for key in ("today", "last_7_days", "last_30_days"):
        report[key] = round(report[key], 4)
    return report
