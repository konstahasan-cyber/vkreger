"""IMAGE_PROMPT_AGENT — standalone use (covers, avatars, regenerating a post image)."""
from __future__ import annotations

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import render_blocks
from app.openai.schema import obj, string
from app.openai.service import AIService

INSTRUCTIONS = COMMON_RULES + """
Роль: IMAGE_PROMPT_AGENT. Составь промпт на английском для генерации изображения: сюжет, композиция,
стиль, освещение, палитра. Никакого текста, логотипов и узнаваемых реальных людей на изображении.
"""
SCHEMA = obj({"prompt": string()})


def image_prompt_for(ai: AIService, project, purpose: str, source_text: str, *, automatic: bool = False) -> str:  # noqa: ANN001
    style = (project.setup_proposal or {}).get("design", {}).get("style", "")
    data = ai.run(
        operation="image_prompt",
        agent=AgentRole.IMAGE_PROMPT_AGENT.value,
        instructions=INSTRUCTIONS,
        input_text=render_blocks({"purpose": purpose, "brand_style": style, "source": source_text[:1500]}),
        schema=SCHEMA,
        project_id=project.id,
        automatic=automatic,
        max_output_tokens=800,
    )
    return data["prompt"]
