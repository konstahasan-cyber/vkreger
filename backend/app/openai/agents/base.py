from __future__ import annotations

from enum import Enum


class AgentRole(str, Enum):
    STRATEGIST = "STRATEGIST"
    COPYWRITER = "COPYWRITER"
    EDITOR = "EDITOR"
    IMAGE_PROMPT_AGENT = "IMAGE_PROMPT_AGENT"
    ANALYST = "ANALYST"
    COMMUNITY_MANAGER = "COMMUNITY_MANAGER"


COMMON_RULES = (
    "Ты работаешь внутри системы ведения сообществ ВКонтакте. Пиши по-русски, если не сказано иначе. "
    "Используй только факты из переданного контекста; не выдумывай цены, адреса, отзывы, статистику, "
    "гарантии и акции. Соблюдай правила ВКонтакте и законодательство РФ о рекламе. "
    "Ответ — строго JSON по заданной схеме."
)
