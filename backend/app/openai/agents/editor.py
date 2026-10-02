"""EDITOR: free local cleanup of common AI clichés + optional separate LLM pass."""
from __future__ import annotations

import re
from typing import Any

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import brand_context, render_blocks
from app.openai.schema import arr, obj, string
from app.openai.service import AIService

# Phrases that make texts look machine-written. Removed (with the following comma) locally.
CLICHES = [
    r"в современном мире",
    r"не секрет,? что",
    r"давайте разберёмся",
    r"давайте разберемся",
    r"важно отметить,? что",
    r"стоит отметить,? что",
    r"следует отметить,? что",
    r"в заключение(?: хочется сказать)?",
    r"в эпоху цифровых технологий",
    r"ни для кого не секрет",
    r"окунитесь в мир",
    r"погрузитесь в мир",
    r"в этой статье мы",
]
_CLICHE_RE = re.compile(r"(?i)\b(?:" + "|".join(CLICHES) + r")\b[,:]?\s*")


def _capitalize_sentences(text: str) -> str:
    return re.sub(r"(^|[.!?]\s+|\n\s*)([a-zа-яё])", lambda m: m.group(1) + m.group(2).upper(), text)


def local_cleanup(text: str) -> tuple[str, list[str]]:
    found = [m.group(0).strip(" ,:") for m in _CLICHE_RE.finditer(text)]
    cleaned = _CLICHE_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # VK doesn't render markdown — strip **bold** and leading '#' headers
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"(?m)^#{1,6}\s+", "", cleaned)
    if found:
        cleaned = _capitalize_sentences(cleaned)
    return cleaned.strip(), found


EDIT_INSTRUCTIONS = COMMON_RULES + """
Роль: EDITOR. Отредактируй пост: убери воду, повторы, канцелярит и шаблонные AI-фразы, сохрани смысл,
факты, CTA и tone of voice. Не добавляй новых фактов. Верни финальный текст и список правок.
"""
EDIT_SCHEMA = obj({"text": string(), "changes": arr(string())})


def edit_post(ai: AIService, project, text: str, *, automatic: bool = False) -> dict[str, Any]:  # noqa: ANN001
    return ai.run(
        operation="post_edit",
        agent=AgentRole.EDITOR.value,
        instructions=EDIT_INSTRUCTIONS,
        input_text=render_blocks({"brand_context": brand_context(project), "post": text}),
        schema=EDIT_SCHEMA,
        project_id=project.id,
        automatic=automatic,
    )
