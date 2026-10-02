"""Projects: CRUD, AI setup (strategy), content plan."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationAppError
from app.models.content import ContentPlanItem, Rubric, Strategy
from app.models.enums import PlanItemStatus, ProjectStatus
from app.models.project import Project
from app.openai.agents import strategist
from app.openai.service import AIService

DEFAULT_POSTING_TIMES = ["10:00", "19:00"]
KNOWN_RUBRICS = ["educational", "case", "faq", "product", "sales", "expert", "news", "engagement"]


def get_project(db: Session, project_id: int) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"project #{project_id} not found")
    return project


def active_strategy(db: Session, project_id: int) -> Strategy | None:
    return db.execute(
        select(Strategy).where(Strategy.project_id == project_id, Strategy.is_active.is_(True))
        .order_by(Strategy.version.desc()).limit(1)
    ).scalar_one_or_none()


def save_strategy(db: Session, project_id: int, data: dict, *, source: str, reasoning: str | None = None) -> Strategy:
    current = active_strategy(db, project_id)
    version = (current.version + 1) if current else 1
    db.execute(update(Strategy).where(Strategy.project_id == project_id).values(is_active=False))
    strategy = Strategy(project_id=project_id, version=version, is_active=True, source=source, data=data,
                        reasoning=reasoning)
    db.add(strategy)
    db.flush()
    return strategy


def _slug(code: str) -> str:
    import re

    code = re.sub(r"[^a-z0-9_]+", "_", (code or "").lower()).strip("_")
    return code[:60] or "general"


def apply_rubrics(db: Session, project: Project, rubrics: list[dict]) -> None:
    existing = {r.code: r for r in project.rubrics}
    seen = set()
    for item in rubrics:
        code = _slug(item.get("code", ""))
        if code in seen:
            continue
        seen.add(code)
        rubric = existing.get(code)
        if rubric is None:
            rubric = Rubric(project_id=project.id, code=code, name=item.get("name") or code)
            project.rubrics.append(rubric)
        rubric.name = item.get("name") or rubric.name
        rubric.description = item.get("description") or rubric.description
        rubric.weight = float(item.get("weight") or 1.0)
        rubric.is_active = True
    db.flush()


def run_setup(db: Session, project: Project, *, force: bool = False, ai: AIService | None = None) -> dict:
    """STRATEGIST: one request → analysis, names, description, design, rubrics, strategy."""
    ai = ai or AIService(db)
    project.status = ProjectStatus.ANALYZING.value
    db.flush()
    data = strategist.project_setup(ai, project, force=force)
    project.setup_proposal = data
    project.context_summary = data.get("context_summary")
    community = data.get("community", {})
    names = community.get("name_options") or [project.business_name]
    project.brand = {
        "community_name": names[0],
        "cta_style": community.get("cta_style"),
        "key_messages": community.get("key_messages", []),
        "design": data.get("design", {}),
    }
    project.content_rules = data.get("content_rules", {})
    apply_rubrics(db, project, data.get("rubrics", []))
    strategy = data.get("strategy", {})
    save_strategy(db, project.id, strategy, source="setup")
    best_times = [t for t in strategy.get("best_times", []) if isinstance(t, str) and len(t) == 5 and t[2] == ":"]
    if best_times and (not project.posting_times or project.posting_times == DEFAULT_POSTING_TIMES):
        project.posting_times = best_times
    project.status = ProjectStatus.PROPOSAL_READY.value
    db.flush()
    return data


def generate_content_plan(db: Session, project: Project, *, days: int = 7, count: int | None = None,
                          automatic: bool = False, force: bool = False, ai: AIService | None = None) -> list[ContentPlanItem]:
    if not project.rubrics:
        raise ValidationAppError("Project has no rubrics: run the AI setup first")
    ai = ai or AIService(db)
    if count is None:
        per_week = project.posts_per_week or (project.posts_per_day or 1) * 7
        if project.posts_per_day:
            per_week = project.posts_per_day * 7
        count = max(1, round(per_week * days / 7))
    count = min(count, 60)
    strategy = active_strategy(db, project.id)
    items = strategist.content_plan(ai, db, project, count=count, days=days, strategy=strategy.data if strategy else None,
                                    automatic=automatic, force=force)
    codes = {r.code for r in project.rubrics if r.is_active}
    fallback = next(iter(sorted(codes)))
    start = datetime.now(UTC)
    created = []
    for item in items[:count]:
        code = _slug(item.get("rubric_code", ""))
        plan_item = ContentPlanItem(
            project_id=project.id,
            rubric_code=code if code in codes else fallback,
            topic=(item.get("topic") or "").strip()[:2000],
            angle=item.get("angle"),
            planned_for=start + timedelta(days=max(0, int(item.get("day_offset") or 0))),
            status=PlanItemStatus.PLANNED.value,
        )
        if plan_item.topic:
            db.add(plan_item)
            created.append(plan_item)
    db.flush()
    return created
