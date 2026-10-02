"""Anti-repetition checks: semantic (embeddings) + lexical (titles, topics, CTA)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, undefer

from app.models.content import Post
from app.models.enums import PostStatus

_WORD = re.compile(r"[\wё]+", re.I)
_STOP = {"и", "в", "на", "с", "по", "для", "как", "что", "это", "не", "к", "о", "от", "из", "за", "а", "у", "the", "a"}


def normalize(text: str | None) -> str:
    return " ".join(w for w in _WORD.findall((text or "").lower().replace("ё", "е")) if w not in _STOP)


def lexical_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    jaccard = len(sa & sb) / len(sa | sb) if sa | sb else 0.0
    return round(max(seq, jaccard), 4)


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


@dataclass
class UniquenessReport:
    ok: bool
    max_semantic: float = 0.0
    max_title: float = 0.0
    reasons: list[str] = field(default_factory=list)
    similar_post_ids: list[int] = field(default_factory=list)
    avoid_hints: list[str] = field(default_factory=list)


def recent_posts(db: Session, project_id: int, limit: int, exclude_id: int | None = None) -> list[Post]:
    query = (
        select(Post)
        .options(undefer(Post.embedding))
        .where(Post.project_id == project_id, Post.status != PostStatus.FAILED.value)
        .order_by(Post.created_at.desc())
        .limit(limit)
    )
    if exclude_id:
        query = query.where(Post.id != exclude_id)
    return list(db.execute(query).scalars())


def check_uniqueness(
    db: Session,
    project_id: int,
    *,
    title: str | None,
    topic: str | None,
    cta: str | None,
    embedding: list[float] | None,
    window: int,
    semantic_threshold: float,
    title_threshold: float,
    cta_window: int,
    exclude_id: int | None = None,
) -> UniquenessReport:
    report = UniquenessReport(ok=True)
    posts = recent_posts(db, project_id, window, exclude_id)
    for index, post in enumerate(posts):
        t_sim = max(lexical_similarity(title, post.title), lexical_similarity(topic, post.topic))
        report.max_title = max(report.max_title, t_sim)
        if t_sim >= title_threshold:
            report.reasons.append(f"title/topic similar to post #{post.id} ({t_sim:.2f})")
            report.similar_post_ids.append(post.id)
            report.avoid_hints.append(post.title or post.topic or "")
        if embedding and post.embedding:
            s_sim = cosine(embedding, post.embedding)
            report.max_semantic = max(report.max_semantic, s_sim)
            if s_sim >= semantic_threshold:
                report.reasons.append(f"semantically similar to post #{post.id} ({s_sim:.2f})")
                report.similar_post_ids.append(post.id)
                report.avoid_hints.append(post.topic or post.title or "")
        if cta and index < cta_window and post.cta and lexical_similarity(cta, post.cta) >= 0.85:
            report.reasons.append(f"CTA repeats post #{post.id}")
            report.avoid_hints.append(f"CTA «{post.cta}»")
    report.ok = not report.reasons
    report.max_semantic = round(report.max_semantic, 4)
    report.similar_post_ids = sorted(set(report.similar_post_ids))
    report.avoid_hints = list(dict.fromkeys(h for h in report.avoid_hints if h))
    return report
