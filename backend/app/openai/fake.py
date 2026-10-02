"""Deterministic offline provider (AI_PROVIDER=fake) for tests and demo setups without an API key.

It walks the JSON Schema to produce a valid object and fills well-known operations with
plausible values.  It never calls the network.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any

from app.openai.provider import EmbeddingResult, LLMResult, TokenUsage

_RUBRICS = ["educational", "case", "faq", "product", "sales", "expert", "news", "engagement"]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _sample(schema: dict[str, Any], name: str, seed: int) -> Any:
    types = schema.get("type")
    if isinstance(types, list):
        types = next((t for t in types if t != "null"), "null")
    if "enum" in schema:
        options = [o for o in schema["enum"] if o is not None]
        return options[seed % len(options)]
    if types == "object":
        return {k: _sample(v, k, seed + i) for i, (k, v) in enumerate(schema["properties"].items())}
    if types == "array":
        return [_sample(schema["items"], name, seed + i) for i in range(3)]
    if types == "string":
        return f"{name} #{seed % 1000}"
    if types == "number":
        return round(0.5 + (seed % 50) / 100, 2)
    if types == "integer":
        return seed % 7
    if types == "boolean":
        return False
    return None


class FakeProvider:
    name = "fake"

    def complete_json(self, *, model: str, instructions: str, input_text: str, schema: dict[str, Any],
                      schema_name: str, max_output_tokens: int, cache_key: str | None = None) -> LLMResult:
        seed = _seed(input_text)
        data = _sample(schema, schema_name, seed)
        handler = getattr(self, f"_op_{schema_name}", None)
        if handler:
            data.update(handler(input_text, seed))
        usage = TokenUsage(input_tokens=len(instructions + input_text) // 3, output_tokens=len(str(data)) // 3)
        return LLMResult(data=data, model=model, usage=usage)

    def embed(self, *, model: str, texts: list[str]) -> EmbeddingResult:
        vectors = []
        for text in texts:
            vec = [0.0] * 64
            for word in re.findall(r"\w+", text.lower()):
                vec[_seed(word) % 64] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return EmbeddingResult(vectors=vectors, model=model,
                               usage=TokenUsage(input_tokens=sum(len(t) // 3 for t in texts)))

    # ---- operation specific values
    @staticmethod
    def _business(input_text: str) -> str:
        match = re.search(r"Бизнес: (.+)", input_text) or re.search(r"Сообщество: (.+)", input_text)
        return match.group(1).strip() if match else "Компания"

    def _op_project_setup(self, input_text: str, seed: int) -> dict:
        biz = self._business(input_text)
        rubrics = [
            {"code": code, "name": code.capitalize(), "description": f"Рубрика {code} для {biz}", "weight": 1.0}
            for code in _RUBRICS[:6]
        ]
        return {
            "context_summary": f"{biz}: краткое резюме бизнеса, ЦА и УТП для генерации контента.",
            "community": {
                "name_options": [f"{biz}", f"{biz} | Официально", f"{biz} — полезное", f"{biz} Club", f"Про {biz}"],
                "description": f"Официальное сообщество {biz}. Полезные советы, кейсы и ответы на вопросы.",
                "status": f"{biz}: пишите в сообщения — ответим",
                "cta_style": "Мягкий призыв написать в сообщения сообщества",
                "key_messages": ["Качество", "Честные условия", "Забота о клиенте"],
            },
            "rubrics": rubrics,
            "strategy": {
                "positioning": f"{biz} — эксперт в своей нише",
                "content_pillars": ["Польза", "Доверие", "Продукт"],
                "rubric_mix": [{"code": r["code"], "share": round(100 / len(rubrics), 1)} for r in rubrics],
                "best_times": ["10:00", "19:00"],
                "kpis": ["ER > 3%", "10 лидов в месяц"],
            },
            "content_rules": {"do": ["Конкретика", "Примеры"], "dont": ["Кликбейт"], "post_length": "600-1000 символов"},
            "pinned_post": {"title": f"Добро пожаловать в {biz}",
                            "text": f"Привет! Это сообщество {biz}. Здесь — польза, кейсы и ответы. Пишите в сообщения!"},
        }

    def _op_content_plan(self, input_text: str, seed: int) -> dict:
        count_match = re.search(r"Нужно тем: (\d+)", input_text)
        count = int(count_match.group(1)) if count_match else 5
        codes = re.findall(r"(\b[a-z_]+) — ", input_text) or _RUBRICS[:4]
        items = []
        for i in range(count):
            code = codes[i % len(codes)]
            items.append({"rubric_code": code, "topic": f"Тема {seed % 997 + i}: {code} идея №{i + 1}",
                          "angle": f"Угол подачи {i + 1}", "day_offset": i})
        return {"items": items}

    def _op_post_compose(self, input_text: str, seed: int) -> dict:
        topic_match = re.search(r"Тема: (.+)", input_text)
        topic = topic_match.group(1).strip() if topic_match else f"Тема {seed}"
        variant = seed % 10000
        return {
            "title": f"{topic} ({variant})",
            "topic": topic,
            "text": f"{topic}.\n\nПодробный разбор вариант {variant}. Важно отметить, что это пример текста.\n\n"
                    f"Напишите нам в сообщения — подскажем.\n\n#пример #vk",
            "cta": f"Напишите нам в сообщения (вариант {variant % 7})",
            "hashtags": ["#пример", "#vk"],
            "image_prompt": f"Minimalist illustration about {topic}, soft light, no text",
            "editor_notes": ["Убраны повторы"],
        }

    def _op_inbox_triage(self, input_text: str, seed: int) -> dict:
        text = input_text.lower()
        cls = "OTHER"
        if any(w in text for w in ("купить", "заказать", "записаться", "хочу", "свяжитесь")):
            cls = "LEAD"
        elif "?" in text or any(w in text for w in ("сколько", "как ", "где ")):
            cls = "QUESTION"
        elif any(w in text for w in ("ужас", "плохо", "обман", "верните")):
            cls = "NEGATIVE"
        elif "http" in text or "заработок" in text:
            cls = "SPAM"
        reply = None if cls == "SPAM" else {
            "LEAD": "Спасибо за интерес! Подскажите, как к вам обращаться и куда удобнее ответить? Менеджер свяжется.",
            "QUESTION": "Спасибо за вопрос! Уточним детали и ответим. Напишите, пожалуйста, в сообщения сообщества.",
            "NEGATIVE": "Нам очень жаль, что так вышло. Напишите, пожалуйста, в сообщения — разберёмся.",
            "OTHER": "Спасибо!",
        }[cls]
        return {"classification": cls, "confidence": 0.9, "reply": reply, "needs_operator": cls in ("LEAD", "NEGATIVE"),
                "lead": {"name": None, "contact": None, "need": "интересуется услугой" if cls == "LEAD" else None},
                "reason": "keyword heuristics (fake provider)"}

    def _op_analytics_review(self, input_text: str, seed: int) -> dict:
        return {"summary": "Стабильные показатели", "change_strategy": False, "rubric_weights": [],
                "best_times": ["10:00", "19:00"], "new_ideas": [{"rubric_code": "faq", "topic": "Новый FAQ"}]}
