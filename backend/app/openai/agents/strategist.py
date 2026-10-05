"""STRATEGIST: business analysis, community concept, rubrics, strategy, content plan."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import (
    analytics_summary,
    brand_context,
    content_rules,
    now_local_hint,
    project_brief,
    project_context,
    recent_posts_summary,
    render_blocks,
)
from app.openai.schema import arr, integer, number, obj, string
from app.openai.service import AIService

SETUP_INSTRUCTIONS = COMMON_RULES + """
Роль: STRATEGIST — SMM-стратег. По брифу бизнеса за один проход:
1) проанализируй бизнес и ЦА (сегменты, боли, мотивы, УТП);
2) предложи 5 вариантов названия сообщества (до 48 символов, без кавычек и спама ключевиками);
3) описание сообщества (до 1500 символов, с пользой для подписчика и призывом), статус (до 139 символов);
4) оформление: палитра (HEX), визуальный стиль, промпты для аватара и обложки (на английском, без текста на изображении);
5) рубрики (5-8; code латиницей snake_case из набора educational, case, faq, product, sales, expert, news, engagement или своих);
6) стратегию: позиционирование, контент-столпы, доли рубрик (сумма 100), лучшие времена публикаций (HH:MM), KPI;
7) правила контента (do/dont, длина) и закреплённый пост (знакомство + ценность + CTA);
8) context_summary — сжатое резюме бизнеса до 700 символов: его будут передавать вместо брифа во все следующие запросы.
"""

SETUP_SCHEMA = obj({
    "context_summary": string("Сжатое резюме бизнеса и ЦА, до 700 символов"),
    "analysis": obj({
        "business_summary": string(),
        "audience_segments": arr(obj({"name": string(), "pains": arr(string()), "motives": arr(string())})),
        "usp": arr(string()),
        "risks": arr(string()),
    }),
    "community": obj({
        "name_options": arr(string()),
        "description": string(),
        "status": string(),
        "cta_style": string(),
        "key_messages": arr(string()),
    }),
    "design": obj({
        "colors": arr(string()),
        "style": string(),
        "avatar_prompt": string(),
        "cover_prompt": string(),
    }),
    "rubrics": arr(obj({"code": string(), "name": string(), "description": string(), "weight": number()})),
    "strategy": obj({
        "positioning": string(),
        "content_pillars": arr(string()),
        "rubric_mix": arr(obj({"code": string(), "share": number()})),
        "best_times": arr(string("HH:MM")),
        "kpis": arr(string()),
    }),
    "content_rules": obj({"do": arr(string()), "dont": arr(string()), "post_length": string()}),
    "pinned_post": obj({"title": string(), "text": string()}),
})


def _brand_block(project) -> str:  # noqa: ANN001
    style = (project.brand or {}).get("style") or {}
    if not style:
        return ""
    return "\n".join([
        "Фирменный стиль уже определён по сайту компании — оформление и промпты делай в нём.",
        f"Компания: {style.get('summary', '')}",
        f"Палитра: {', '.join(style.get('palette') or [])}",
        f"Визуальный стиль: {style.get('visual_style', '')}",
        f"Тон текстов: {style.get('tone_of_voice', '')}",
        "Факты: " + "; ".join((style.get("business_facts") or [])[:10]),
    ])


def project_setup(ai: AIService, project, *, force: bool = False) -> dict[str, Any]:  # noqa: ANN001
    return ai.run(
        operation="project_setup",
        agent=AgentRole.STRATEGIST.value,
        instructions=SETUP_INSTRUCTIONS,
        input_text=render_blocks({"brief": project_brief(project), "brand_style": _brand_block(project)}),
        schema=SETUP_SCHEMA,
        project_id=project.id,
        force=force,
        max_output_tokens=6000,
    )


PLAN_INSTRUCTIONS = COMMON_RULES + """
Роль: STRATEGIST. Составь контент-план из N тем. Темы должны быть разными по смыслу,
не повторять уже опубликованные (см. recent_posts_summary) и соответствовать долям рубрик.
Для каждой темы укажи rubric_code (только из списка рубрик), конкретную тему, угол подачи (angle)
и смещение в днях от начала периода (day_offset).
"""

PLAN_SCHEMA = obj({
    "items": arr(obj({"rubric_code": string(), "topic": string(), "angle": string(), "day_offset": integer()})),
})


def content_plan(ai: AIService, db: Session, project, *, count: int, days: int, strategy: dict | None,  # noqa: ANN001
                 automatic: bool = False, force: bool = False) -> list[dict]:
    strategy_block = ""
    if strategy:
        mix = ", ".join(f"{m.get('code')}: {m.get('share')}%" for m in strategy.get("rubric_mix", []))
        pillars = "; ".join(strategy.get("content_pillars", [])[:6])
        strategy_block = f"Позиционирование: {strategy.get('positioning', '')}\nСтолпы: {pillars}\nДоли рубрик: {mix}"
    blocks = {
        "project_context": project_context(project),
        "brand_context": brand_context(project),
        "content_rules": content_rules(project, db),
        "strategy": strategy_block,
        "recent_posts_summary": recent_posts_summary(db, project.id),
        "analytics_summary": analytics_summary(db, project.id),
        "task": f"Сегодня {now_local_hint(project.timezone)}. Нужно тем: {count}, период: {days} дн.",
    }
    data = ai.run(
        operation="content_plan",
        agent=AgentRole.STRATEGIST.value,
        instructions=PLAN_INSTRUCTIONS,
        input_text=render_blocks(blocks),
        schema=PLAN_SCHEMA,
        project_id=project.id,
        automatic=automatic,
        force=force,
    )
    return data.get("items", [])
