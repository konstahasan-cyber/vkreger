"""Minimal context blocks for AI requests.

Instead of sending the whole project history, each agent receives only the blocks it
needs.  Blocks are compact text, built from pre-summarised data stored on the project
(``context_summary``, ``brand``, ``content_rules``) and from aggregated queries.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.content import Post, Rubric
from app.models.enums import PostStatus
from app.models.project import Project

TONE_LABELS = {
    "expert": "экспертный, уверенный, с фактами",
    "simple": "простой, понятный, без сложных терминов",
    "selling": "продающий, с акцентом на выгоды и действие",
    "friendly": "дружелюбный, тёплый, на «вы» без официоза",
}
GOAL_LABELS = {
    "leads": "получение заявок (лидов)",
    "sales": "продажи",
    "reach": "охваты и рост аудитории",
    "expertise": "демонстрация экспертности",
    "traffic": "трафик на сайт",
}


def _clip(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def project_brief(project: Project) -> str:
    """Raw project data — used once, for the initial business analysis."""
    lines = [
        f"Бизнес: {project.business_name}",
        f"Тематика: {project.theme or '-'}; ниша: {project.niche or '-'}",
        f"Город/регион: {project.city or '-'}",
        f"Целевая аудитория (со слов клиента): {_clip(project.target_audience, 600) or '-'}",
        f"Продукт: {_clip(project.product_description, 1200) or '-'}",
        f"Преимущества: {_clip(project.advantages, 800) or '-'}",
        f"Сайт: {project.website or '-'}; контакты: {_clip(project.contacts, 200) or '-'}",
        f"Главная цель: {GOAL_LABELS.get(project.goal, project.goal)}",
        f"Частота: {project.posts_per_day or '-'} в день / {project.posts_per_week or '-'} в неделю",
        f"Tone of voice: {tone_description(project)}",
    ]
    return "\n".join(lines)


def tone_description(project: Project) -> str:
    if project.tone == "custom" and project.custom_tone_prompt:
        return _clip(project.custom_tone_prompt, 400)
    return TONE_LABELS.get(project.tone, project.tone)


def project_context(project: Project) -> str:
    if project.context_summary:
        return _clip(project.context_summary, 1500)
    return _clip(project_brief(project), 1500)


def brand_context(project: Project) -> str:
    brand = project.brand or {}
    community = project.community
    parts = [
        f"Сообщество: {community.name if community else brand.get('community_name') or project.business_name}",
        f"Tone of voice: {tone_description(project)}",
        f"Цель: {GOAL_LABELS.get(project.goal, project.goal)}",
    ]
    if brand.get("cta_style"):
        parts.append(f"Стиль CTA: {_clip(brand['cta_style'], 200)}")
    if brand.get("key_messages"):
        parts.append("Ключевые сообщения: " + "; ".join(_clip(m, 120) for m in brand["key_messages"][:5]))
    style = brand.get("style") or {}
    if style.get("tone_of_voice"):
        parts.append(f"Как пишет компания: {_clip(style['tone_of_voice'], 250)}")
    if style.get("key_phrases"):
        parts.append("Фирменные формулировки: " + "; ".join(_clip(p, 80) for p in style["key_phrases"][:6]))
    if project.website:
        parts.append(f"Сайт: {project.website}")
    if project.contacts:
        parts.append(f"Контакты: {_clip(project.contacts, 150)}")
    return "\n".join(parts)


def content_rules(project: Project, db: Session | None = None) -> str:
    rules = project.content_rules or {}
    lines = []
    rubrics = project.rubrics
    if rubrics:
        lines.append("Рубрики: " + "; ".join(
            f"{r.code} — {_clip(r.description or r.name, 90)}" for r in rubrics if r.is_active))
    if rules.get("do"):
        lines.append("Делать: " + "; ".join(_clip(x, 100) for x in rules["do"][:8]))
    if rules.get("dont"):
        lines.append("Не делать: " + "; ".join(_clip(x, 100) for x in rules["dont"][:8]))
    if rules.get("brand_tone"):
        lines.append(f"Тон бренда: {_clip(rules['brand_tone'], 200)}")
    from app.content.personas import project_persona

    persona = project_persona(project)
    if persona:
        lines.append(f"Длина поста: {persona['length']}. Хештегов: 2-5. Эмодзи: {persona['emoji']}.")
    else:
        length = rules.get("post_length") or "600-1200 символов"
        lines.append(f"Длина поста: {length}. Хештегов: 2-5. Эмодзи — умеренно.")
    lines.append("Запрещено: выдумывать цены/факты/отзывы, которых нет в данных; кликбейт; канцелярит; "
                 "фразы-штампы («в современном мире», «не секрет, что», «давайте разберёмся», «важно отметить»).")
    return "\n".join(lines)


def recent_posts_summary(db: Session, project_id: int, limit: int | None = None) -> str:
    limit = limit or settings.RECENT_POSTS_WINDOW
    rows = db.execute(
        select(Post.category, Post.title, Post.topic, Post.cta)
        .where(Post.project_id == project_id, Post.status != PostStatus.FAILED.value)
        .order_by(Post.created_at.desc())
        .limit(limit)
    ).all()
    if not rows:
        return "Публикаций ещё не было."
    return "\n".join(
        f"- [{c or '-'}] {_clip(t or tp, 80)} | CTA: {_clip(cta, 50) or '-'}" for c, t, tp, cta in rows
    )


def sibling_project_ids(db: Session, project: Project) -> list[int]:
    """Other active projects of the same network (groups on one topic)."""
    if not project.network:
        return []
    from app.models.enums import ProjectStatus

    return list(db.execute(
        select(Project.id).where(Project.network == project.network, Project.id != project.id,
                                 Project.status != ProjectStatus.ARCHIVED.value)
    ).scalars())


def network_posts_summary(db: Session, project: Project, limit: int = 30) -> str:
    """What sibling groups already have: titles and first lines — so the model doesn't repeat them."""
    ids = sibling_project_ids(db, project)
    if not ids:
        return ""
    rows = db.execute(
        select(Post.title, Post.topic, Post.text)
        .where(Post.project_id.in_(ids), Post.status != PostStatus.FAILED.value)
        .order_by(Post.created_at.desc())
        .limit(limit)
    ).all()
    if not rows:
        return ""
    lines = ["Другие группы на эту же тему уже написали (НЕ повторяй эти темы, заголовки, первые фразы и структуру):"]
    for title, topic, text in rows:
        first = (text or "").strip().split("\n", 1)[0]
        lines.append(f"- {_clip(title or topic, 70)} | начало: «{_clip(first, 70)}»")
    return "\n".join(lines)


def network_plan_topics(db: Session, project: Project, limit: int = 80) -> str:
    """Topics already planned or written by sibling groups — for a content plan that doesn't overlap."""
    from app.models.content import ContentPlanItem

    ids = sibling_project_ids(db, project)
    if not ids:
        return ""
    planned = db.execute(
        select(ContentPlanItem.topic).where(ContentPlanItem.project_id.in_(ids))
        .order_by(ContentPlanItem.id.desc()).limit(limit)
    ).scalars().all()
    written = db.execute(
        select(Post.topic).where(Post.project_id.in_(ids), Post.topic.is_not(None))
        .order_by(Post.created_at.desc()).limit(limit // 2)
    ).scalars().all()
    topics = list(dict.fromkeys(_clip(t, 90) for t in [*planned, *written] if t))
    if not topics:
        return ""
    return ("Эти темы уже заняты другими группами сети — придумай ДРУГИЕ темы и другие углы подачи:\n"
            + "\n".join(f"- {t}" for t in topics[:limit]))


def analytics_summary(db: Session, project_id: int) -> str:
    from app.analytics.aggregator import aggregate_project

    agg = aggregate_project(db, project_id, last_n=30)
    if not agg["posts_count"]:
        return "Статистики пока нет."
    lines = [
        f"Постов в выборке: {agg['posts_count']}; средние просмотры: {agg['avg_views']}; "
        f"средний ER: {agg['avg_engagement_rate']}%",
    ]
    if agg["by_category"]:
        lines.append("По рубрикам (ER%, постов): " + "; ".join(
            f"{c['category']}: {c['engagement_rate']} ({c['posts']})" for c in agg["by_category"]))
    if agg["best_hours"]:
        lines.append("Лучшие часы публикации: " + ", ".join(f"{h['hour']}:00 (ER {h['engagement_rate']})"
                                                           for h in agg["best_hours"][:3]))
    if agg["top_posts"]:
        lines.append("Лучшие посты: " + "; ".join(f"[{p['category']}] {_clip(p['title'], 60)}"
                                                 for p in agg["top_posts"][:3]))
    if agg["worst_posts"]:
        lines.append("Худшие посты: " + "; ".join(f"[{p['category']}] {_clip(p['title'], 60)}"
                                                 for p in agg["worst_posts"][:3]))
    if agg.get("leads_count") is not None:
        lines.append(f"Лидов за период: {agg['leads_count']}")
    return "\n".join(lines)


def rubric_codes(db: Session, project_id: int) -> list[str]:
    return list(db.execute(
        select(Rubric.code).where(Rubric.project_id == project_id, Rubric.is_active.is_(True))
    ).scalars())


def render_blocks(blocks: dict[str, str]) -> str:
    return "\n\n".join(f"<{name}>\n{body}\n</{name}>" for name, body in blocks.items() if body)


def now_local_hint(tz: str) -> str:
    try:
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo(tz))
    except Exception:  # pragma: no cover
        now = datetime.now(UTC)
    return now.strftime("%Y-%m-%d (%A)")


def days_ago(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
