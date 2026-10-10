"""COPYWRITER + EDITOR + IMAGE_PROMPT_AGENT combined in one request to save tokens."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.content.personas import persona_block
from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import (
    brand_context,
    content_rules,
    network_posts_summary,
    project_context,
    recent_posts_summary,
    render_blocks,
)
from app.openai.schema import arr, obj, string
from app.openai.service import AIService

COMPOSE_INSTRUCTIONS = COMMON_RULES + """
Ты одновременно выполняешь три роли.
COPYWRITER: напиши пост для сообщества ВКонтакте по теме и рубрике. Структура: цепляющий первый абзац,
польза/история/разбор, конкретика, один понятный CTA, соответствующий цели проекта. Без markdown-разметки
(ВКонтакте её не поддерживает), абзацы через пустую строку, эмодзи умеренно.
EDITOR: перечитай текст, убери воду, повторы, канцелярит и шаблонные AI-фразы; проверь, что заголовок,
CTA и тема не повторяют последние публикации (recent_posts_summary).
IMAGE_PROMPT_AGENT: составь промпт (на английском) для генерации иллюстрации к посту: сюжет, композиция,
стиль, освещение; без текста и логотипов на изображении, без узнаваемых реальных людей.
Поле text — финальный текст поста целиком (с CTA и хештегами в конце).
Если передан author_voice — строго пиши этим голосом, в этой структуре и длине: у группы свой узнаваемый стиль.
Если передан network_posts — это посты других групп на ту же тему: твой пост должен отличаться от них темой
или углом, заголовком, первой фразой, структурой, примерами и CTA.
"""

COMPOSE_SCHEMA = obj({
    "title": string("Короткий заголовок/первая строка, до 100 символов"),
    "topic": string("Тема одной фразой — для проверки повторов"),
    "text": string(),
    "cta": string(),
    "hashtags": arr(string()),
    "image_prompt": string(),
    "editor_notes": arr(string("Что исправил редактор")),
})


def compose_post(ai: AIService, db: Session, project, *, rubric_code: str, rubric_desc: str | None,  # noqa: ANN001
                 topic: str, angle: str | None, avoid: list[str] | None = None, automatic: bool = False,
                 force: bool = False, extra_instructions: str | None = None) -> dict[str, Any]:
    task = [f"Рубрика: {rubric_code}" + (f" — {rubric_desc}" if rubric_desc else ""), f"Тема: {topic}"]
    if angle:
        task.append(f"Угол подачи: {angle}")
    if avoid:
        task.append("Слишком похоже на прошлые посты, НЕ повторяй: " + "; ".join(avoid[:5]))
    if extra_instructions:
        task.append(f"Дополнительно: {extra_instructions}")
    blocks = {
        "project_context": project_context(project),
        "brand_context": brand_context(project),
        "content_rules": content_rules(project, db),
        "author_voice": persona_block(project),
        "recent_posts_summary": recent_posts_summary(db, project.id, limit=15),
        "network_posts": network_posts_summary(db, project),
        "task": "\n".join(task),
    }
    return ai.run(
        operation="post_compose",
        agent=f"{AgentRole.COPYWRITER.value}+{AgentRole.EDITOR.value}+{AgentRole.IMAGE_PROMPT_AGENT.value}",
        instructions=COMPOSE_INSTRUCTIONS,
        input_text=render_blocks(blocks),
        schema=COMPOSE_SCHEMA,
        project_id=project.id,
        automatic=automatic,
        force=force,
    )
