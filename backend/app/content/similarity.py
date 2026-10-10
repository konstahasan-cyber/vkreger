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
    return normalized_similarity(normalize(a), normalize(b))


def normalized_similarity(na: str, nb: str, threshold: float | None = None) -> float:
    """Similarity of already normalized strings; with ``threshold`` cheap upper bounds skip hopeless pairs."""
    if not na or not nb:
        return 0.0
    if threshold is not None:
        # word stems (first 5 letters, robust to Russian endings): far-apart strings skip the slow matcher
        sa, sb = {w[:5] for w in na.split()}, {w[:5] for w in nb.split()}
        if len(sa & sb) / len(sa | sb) < threshold / 2:
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


def first_line(text: str | None) -> str:
    return (text or "").strip().split("\n", 1)[0][:200]


def recent_posts(db: Session, project_id: int | list[int], limit: int, exclude_id: int | None = None) -> list[Post]:
    ids = project_id if isinstance(project_id, list) else [project_id]
    if not ids:
        return []
    query = (
        select(Post)
        .options(undefer(Post.embedding))
        .where(Post.project_id.in_(ids), Post.status != PostStatus.FAILED.value)
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
    sibling_ids: list[int] | None = None,
    sibling_window: int = 120,
    opening: str | None = None,
) -> UniquenessReport:
    report = UniquenessReport(ok=True)
    posts = recent_posts(db, project_id, window, exclude_id)
    _compare(report, posts, title=title, topic=topic, cta=cta, embedding=embedding,
             semantic_threshold=semantic_threshold, title_threshold=title_threshold, cta_window=cta_window)
    if sibling_ids:
        # posts of other groups on the same topic: same checks plus the opening line
        siblings = recent_posts(db, sibling_ids, sibling_window, exclude_id)
        _compare(report, siblings, title=title, topic=topic, cta=None, embedding=embedding,
                 semantic_threshold=semantic_threshold, title_threshold=title_threshold, cta_window=0,
                 label="другой группы ", use_topic=False)
        if opening:
            for post in siblings:
                if lexical_similarity(opening, first_line(post.text)) >= 0.8:
                    report.reasons.append(f"opening line repeats post #{post.id} of another group")
                    report.similar_post_ids.append(post.id)
                    report.avoid_hints.append(f"начало «{first_line(post.text)[:80]}»")
    report.ok = not report.reasons
    report.max_semantic = round(report.max_semantic, 4)
    report.similar_post_ids = sorted(set(report.similar_post_ids))
    report.avoid_hints = list(dict.fromkeys(h for h in report.avoid_hints if h))
    return report


def _compare(report: UniquenessReport, posts: list[Post], *, title: str | None, topic: str | None, cta: str | None,
             embedding: list[float] | None, semantic_threshold: float, title_threshold: float, cta_window: int,
             label: str = "", use_topic: bool = True) -> None:
    # for other groups only what readers see counts (title, opening, meaning), not the internal plan topic
    for index, post in enumerate(posts):
        t_sim = lexical_similarity(title, post.title)
        if use_topic:
            t_sim = max(t_sim, lexical_similarity(topic, post.topic))
        report.max_title = max(report.max_title, t_sim)
        if t_sim >= title_threshold:
            report.reasons.append(f"title/topic similar to {label}post #{post.id} ({t_sim:.2f})")
            report.similar_post_ids.append(post.id)
            report.avoid_hints.append(post.title or post.topic or "")
        if embedding and post.embedding:
            s_sim = cosine(embedding, post.embedding)
            report.max_semantic = max(report.max_semantic, s_sim)
            if s_sim >= semantic_threshold:
                report.reasons.append(f"semantically similar to {label}post #{post.id} ({s_sim:.2f})")
                report.similar_post_ids.append(post.id)
                report.avoid_hints.append(post.topic or post.title or "")
        if cta and index < cta_window and post.cta and lexical_similarity(cta, post.cta) >= 0.85:
            report.reasons.append(f"CTA repeats post #{post.id}")
            report.avoid_hints.append(f"CTA «{post.cta}»")
