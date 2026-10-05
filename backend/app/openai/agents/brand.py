"""BRAND agent: turns website signals into a compact brand style guide that is then
reused for the community avatar/cover, post images and the tone of texts."""
from __future__ import annotations

from typing import Any

from app.openai.agents.base import COMMON_RULES, AgentRole
from app.openai.context import project_brief, render_blocks
from app.openai.schema import arr, obj, string
from app.openai.service import AIService

INSTRUCTIONS = COMMON_RULES + """
Роль: бренд-дизайнер и редактор. По данным с сайта компании (цвета, шрифты, заголовки, тексты) опиши
фирменный стиль так, чтобы по нему можно было оформлять сообщество ВКонтакте и картинки к постам:
- palette: 3-6 фирменных цветов в HEX (бери с сайта, не выдумывай, если они есть);
- visual_style: стиль визуала одной-двумя фразами (минимализм, фото, иллюстрации, настроение);
- image_style: суффикс для промптов генерации картинок НА АНГЛИЙСКОМ (стиль, палитра словами, освещение,
  композиция; без текста и логотипов на изображении);
- avatar_prompt и cover_prompt: промпты НА АНГЛИЙСКОМ для аватара сообщества (простой узнаваемый знак/символ
  в фирменных цветах, крупно по центру, без текста) и обложки (широкая сцена/паттерн в фирменном стиле,
  без текста, важное по центру);
- tone_of_voice: как пишет компания (по текстам сайта);
- key_phrases: характерные формулировки/обещания с сайта (дословно, до 8);
- business_facts: конкретные факты о продукте, ценах, адресах, условиях из текстов сайта (только то, что есть);
- summary: 2-3 предложения о компании.
"""

SCHEMA = obj({
    "summary": string(),
    "palette": arr(string("HEX")),
    "fonts": arr(string()),
    "visual_style": string(),
    "image_style": string(),
    "avatar_prompt": string(),
    "cover_prompt": string(),
    "tone_of_voice": string(),
    "key_phrases": arr(string()),
    "business_facts": arr(string()),
})


def analyze_brand(ai: AIService, project, signals: dict[str, Any], *, force: bool = False) -> dict[str, Any]:  # noqa: ANN001
    site = [
        f"URL: {signals.get('url') or 'загруженный HTML-файл'}",
        f"Title: {signals.get('title') or '-'}",
        f"Description: {signals.get('description') or '-'}",
        f"Цвета из CSS (по частоте): {', '.join(signals.get('colors') or []) or '-'}",
        f"Шрифты: {', '.join(signals.get('fonts') or []) or '-'}",
        f"Заголовки: {' | '.join((signals.get('headings') or [])[:15]) or '-'}",
        f"Текст страницы: {(signals.get('text') or '')[:4000]}",
    ]
    return ai.run(
        operation="brand_analysis",
        agent=AgentRole.STRATEGIST.value,
        instructions=INSTRUCTIONS,
        input_text=render_blocks({"brief": project_brief(project), "site": "\n".join(site)}),
        schema=SCHEMA,
        project_id=project.id,
        force=force,
        max_output_tokens=3000,
    )
