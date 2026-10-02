"""COMMUNITY_MANAGER: classify incoming comment/message, draft a reply, extract lead fields — one call."""
from __future__ import annotations

from typing import Any

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import brand_context, project_context, render_blocks
from app.openai.schema import number, obj, string
from app.openai.service import AIService

INSTRUCTIONS = COMMON_RULES + """
Роль: COMMUNITY_MANAGER сообщества ВКонтакте. Классифицируй входящее:
QUESTION — вопрос о продукте/услуге/условиях; LEAD — человек готов купить/записаться/просит связаться;
NEGATIVE — жалоба, недовольство; SPAM — реклама, ссылки, мусор; OTHER — всё остальное.
Подготовь короткий вежливый ответ в tone of voice бренда:
- QUESTION: ответь по существу, только на основе контекста; если данных нет — предложи уточнить у менеджера;
- LEAD: НЕ закрывай сложную продажу сам. Поблагодари и попроси базовую информацию (имя, удобный контакт,
  что именно нужно), скажи, что менеджер свяжется. Заполни поля lead тем, что уже известно;
- NEGATIVE: эмпатичный ответ без споров и обещаний компенсаций, needs_operator=true;
- SPAM: reply = null.
"""
SCHEMA = obj({
    "classification": string(enum=["QUESTION", "LEAD", "NEGATIVE", "SPAM", "OTHER"]),
    "confidence": number("0..1"),
    "reply": string(nullable=True),
    "needs_operator": {"type": "boolean"},
    "lead": obj({
        "name": string(nullable=True),
        "contact": string(nullable=True),
        "need": string(nullable=True),
    }),
    "reason": string(),
})


def triage(ai: AIService, project, *, kind: str, text: str, context_hint: str | None = None,  # noqa: ANN001
           automatic: bool = True) -> dict[str, Any]:
    blocks = {
        "project_context": project_context(project),
        "brand_context": brand_context(project),
        "incoming": f"Тип: {'комментарий к посту' if kind == 'comment' else 'личное сообщение сообществу'}\n"
                    + (f"Пост: {context_hint[:300]}\n" if context_hint else "")
                    + f"Текст: {text[:2000]}",
    }
    return ai.run(
        operation="inbox_triage",
        agent=AgentRole.COMMUNITY_MANAGER.value,
        instructions=INSTRUCTIONS,
        input_text=render_blocks(blocks),
        schema=SCHEMA,
        project_id=project.id,
        automatic=automatic,
        max_output_tokens=1200,
    )
