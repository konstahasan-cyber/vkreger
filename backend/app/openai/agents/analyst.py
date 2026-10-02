"""ANALYST: periodic review of aggregated statistics → strategy adjustments."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import analytics_summary, content_rules, project_context, recent_posts_summary, render_blocks
from app.openai.schema import arr, boolean, number, obj, string
from app.openai.service import AIService

INSTRUCTIONS = COMMON_RULES + """
Роль: ANALYST. По агрегированной статистике оцени, что работает, а что нет. Найди повторяющиеся темы,
предложи новые идеи и скорректируй веса рубрик (0.2..3.0) и время публикаций.
Меняй стратегию (change_strategy=true) только при заметных и устойчивых различиях, иначе оставь как есть.
"""
SCHEMA = obj({
    "summary": string(),
    "insights": arr(string()),
    "recommendations": arr(string()),
    "change_strategy": boolean(),
    "rubric_weights": arr(obj({"code": string(), "weight": number()})),
    "best_times": arr(string("HH:MM")),
    "repeated_topics": arr(string()),
    "new_ideas": arr(obj({"rubric_code": string(), "topic": string()})),
})


def review(ai: AIService, db: Session, project, strategy: dict | None, *, automatic: bool = True) -> dict[str, Any]:  # noqa: ANN001
    mix = ", ".join(f"{m.get('code')}: {m.get('share')}%" for m in (strategy or {}).get("rubric_mix", []))
    blocks = {
        "project_context": project_context(project),
        "content_rules": content_rules(project, db),
        "current_strategy": f"Доли рубрик: {mix}; время: {', '.join(project.posting_times or [])}",
        "analytics_summary": analytics_summary(db, project.id),
        "recent_posts_summary": recent_posts_summary(db, project.id, limit=30),
    }
    return ai.run(
        operation="analytics_review",
        agent=AgentRole.ANALYST.value,
        instructions=INSTRUCTIONS,
        input_text=render_blocks(blocks),
        schema=SCHEMA,
        project_id=project.id,
        automatic=automatic,
    )
