"""Networks: many VK groups on one topic, connected in bulk with community keys.

Each group gets its own project (so its own queue, schedule and inbox) and its own author
voice.  Projects of one network share the business brief and the AI strategy, and their
posts are checked for repeats across the whole network.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.content.personas import PERSONAS, persona_for_index, project_persona
from app.content.similarity import first_line, normalize, normalized_similarity, recent_posts
from app.core.exceptions import ValidationAppError
from app.models.community import Community
from app.models.content import Post
from app.models.enums import PostStatus, ProjectStatus
from app.models.project import Project
from app.services import community_service, project_service
from app.vk import factory
from app.vk.client import VKClient

MAX_GROUPS = 200

# Community keys: current "vk1.a.…" keys and older long alphanumeric keys
_KEY = re.compile(r"(vk1\.a\.[A-Za-z0-9_\-.]+|\b[A-Za-z0-9]{60,}\b)")
_GROUP_NUM = re.compile(r"(?:vk\.(?:com|ru)/)?(?:club|public|event)(\d+)", re.I)
_GROUP_URL = re.compile(r"vk\.(?:com|ru)/([A-Za-z0-9_.]+)", re.I)
_BARE_ID = re.compile(r"(?<![\w.])-?(\d{3,12})(?![\w.])")


@dataclass
class ParsedLine:
    line: int
    group: str | None  # numeric id or short name; None — take it from the key
    token: str | None
    label: str | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.token:
            data["token"] = f"{self.token[:8]}…{self.token[-4:]}"  # never echo the whole key back
        return data


def parse_lines(text: str) -> list[ParsedLine]:
    """Parse «ID key», «key», «https://vk.com/club123 key Name» … one group per line.

    Separators may be spaces, tabs, «;», «,» or «|» — whatever came from a spreadsheet or a chat.
    """
    result: list[ParsedLine] = []
    seen_groups: set[str] = set()
    seen_tokens: set[str] = set()
    for number, raw in enumerate((text or "").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keys = _KEY.findall(line)
        rest = _KEY.sub(" ", line)
        group = None
        for pattern in (_GROUP_NUM, _GROUP_URL, _BARE_ID):
            match = pattern.search(rest)
            if match:
                group = match.group(1)
                rest = rest[:match.start()] + " " + rest[match.end():]
                break
        label = re.sub(r"https?://\S*", " ", rest)
        label = " ".join(re.sub(r"[;,|\t]+", " ", label).split()).strip(" -—:") or None
        item = ParsedLine(line=number, group=group, token=keys[0] if keys else None, label=label)
        if not keys:
            item.error = "не найден ключ доступа (он начинается с vk1.a.)"
        elif len(keys) > 1:
            item.error = "в строке два ключа — по одной группе на строку"
        elif group and group in seen_groups:
            item.error = f"группа {group} уже есть выше"
        elif item.token in seen_tokens:
            item.error = "этот ключ уже есть выше"
        if not item.error:
            if group:
                seen_groups.add(group)
            seen_tokens.add(item.token)
        result.append(item)
    if len([r for r in result if not r.error]) > MAX_GROUPS:
        raise ValidationAppError(f"За один раз можно подключить не больше {MAX_GROUPS} групп")
    return result


def network_projects(db: Session, network: str) -> list[Project]:
    return list(db.execute(
        select(Project).where(Project.network == network, Project.status != ProjectStatus.ARCHIVED.value)
        .order_by(Project.id)
    ).scalars())


def list_networks(db: Session) -> list[dict]:
    rows = db.execute(
        select(Project.network, func.count(Project.id))
        .where(Project.network.is_not(None), Project.status != ProjectStatus.ARCHIVED.value)
        .group_by(Project.network).order_by(Project.network)
    ).all()
    return [{"name": name, "projects": count} for name, count in rows]


def network_overview(db: Session, network: str) -> dict:
    projects = network_projects(db, network)
    ids = [p.id for p in projects]
    counts: dict[tuple[int, str], int] = {}
    if ids:
        for project_id, status, count in db.execute(
            select(Post.project_id, Post.status, func.count(Post.id))
            .where(Post.project_id.in_(ids)).group_by(Post.project_id, Post.status)
        ).all():
            counts[(project_id, status)] = count
    items = []
    for p in projects:
        persona = project_persona(p) or {}
        by_status = {s.value: counts.get((p.id, s.value), 0) for s in PostStatus}
        items.append({
            "project_id": p.id, "name": p.name, "status": p.status,
            "community_id": p.community.id if p.community else None,
            "vk_group_id": p.community.vk_group_id if p.community else None,
            "persona": persona.get("name"), "persona_code": persona.get("code"),
            "posts": by_status, "total_posts": sum(by_status.values()),
        })
    return {"name": network, "projects": items}


def assign_persona(db: Session, project: Project, network: str, *, overwrite: bool = False) -> dict:
    """Give the project the next unused author voice of the network."""
    if project_persona(project) and not overwrite:
        return project_persona(project)
    used = [project_persona(p)["code"] for p in network_projects(db, network)
            if p.id != project.id and project_persona(p)]
    free = [p for p in PERSONAS if p["code"] not in used]
    persona = dict(free[0]) if free else persona_for_index(len(used))
    project.brand = {**(project.brand or {}), "persona": persona}
    db.flush()
    return persona


def add_to_network(db: Session, project: Project, network: str) -> Project:
    network = network.strip()[:255]
    if not network:
        raise ValidationAppError("Укажите название сети")
    project.network = network
    assign_persona(db, project, network)
    return project


def resolve_group(token: str, group: str | None) -> dict:
    """Check the key with groups.getById: without an ID VK returns the key's own community."""
    with VKClient(token, transport=factory._transport_override) as client:
        info = client.get_group(group)
    if group and str(info.get("id")) != group and (info.get("screen_name") or "").lower() != group.lower():
        raise ValidationAppError("ключ принадлежит другой группе")
    return info


def template_project(db: Session, network: str, exclude: set[int] | None = None) -> Project | None:
    """A project of the network whose AI strategy can be shared with new groups."""
    for project in network_projects(db, network):
        if project.id in (exclude or set()):
            continue
        if project.rubrics and project.context_summary:
            return project
    return None


def copy_strategy(db: Session, source: Project, target: Project) -> None:
    """Share the business analysis, rubrics, rules and strategy — one STRATEGIST call per network."""
    target.context_summary = source.context_summary
    target.setup_proposal = source.setup_proposal or {}
    keep = {k: v for k, v in (target.brand or {}).items() if k in ("persona", "style", "avatar", "cover")}
    shared = {k: v for k, v in (source.brand or {}).items() if k in ("cta_style", "key_messages", "design")}
    target.brand = {**shared, **keep, "community_name": target.name}
    target.content_rules = dict(source.content_rules or {})
    project_service.apply_rubrics(db, target, [
        {"code": r.code, "name": r.name, "description": r.description, "weight": r.weight}
        for r in source.rubrics if r.is_active
    ])
    strategy = project_service.active_strategy(db, source.id)
    if strategy:
        project_service.save_strategy(db, target.id, strategy.data, source="network")
    db.flush()


def connect_group(db: Session, item: ParsedLine, brief: dict, network: str) -> tuple[Project, bool]:
    """Create (or reuse) the project for one line and connect its community with the key.

    Returns (project, created).
    """
    info = resolve_group(item.token, item.group)
    gid = int(info["id"])
    existing = db.execute(select(Community).where(Community.vk_group_id == gid)).scalar_one_or_none()
    if existing and existing.project_id:
        project = project_service.get_project(db, existing.project_id)
        existing.community_token = item.token
        add_to_network(db, project, network)
        return project, False
    name = (info.get("name") or item.label or f"club{gid}")[:255]
    project = Project(
        name=name, business_name=brief.get("business_name") or name, theme=brief.get("theme"),
        niche=brief.get("niche"), city=brief.get("city"), target_audience=brief.get("target_audience"),
        product_description=brief.get("product_description"), advantages=brief.get("advantages"),
        website=brief.get("website"), contacts=brief.get("contacts"), goal=brief.get("goal") or "leads",
        tone=brief.get("tone") or "friendly", posts_per_day=brief.get("posts_per_day"),
        posts_per_week=brief.get("posts_per_week") or 7, images_enabled=bool(brief.get("images_enabled", False)),
        posting_times=brief.get("posting_times") or ["10:00"], timezone=brief.get("timezone") or "Europe/Moscow",
        setup_proposal={}, brand={}, content_rules={}, status=ProjectStatus.DRAFT.value,
        auto_reply_types=["QUESTION"],
    )
    db.add(project)
    db.flush()
    add_to_network(db, project, network)
    community_service.connect_community(db, project, gid, item.token)
    return project, True


# ---- finding posts that look alike across the network

def similar_pairs(db: Session, network: str, *, semantic_threshold: float, title_threshold: float,
                  limit: int = 200) -> list[dict]:
    """Pairs of posts from different groups of the network that look alike (newest posts first)."""
    import numpy as np

    projects = {p.id: p for p in network_projects(db, network)}
    posts = recent_posts(db, list(projects), limit=600)
    titles = [normalize(p.title) for p in posts]
    openings = [normalize(first_line(p.text)) for p in posts]
    sims = None
    dims = {len(p.embedding) for p in posts if p.embedding}
    if len(dims) == 1:
        dim = dims.pop()
        matrix = np.array([p.embedding if p.embedding else [0.0] * dim for p in posts], dtype=float)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
        sims = matrix @ matrix.T
    pairs = []
    for i, a in enumerate(posts):
        for j in range(i + 1, len(posts)):
            b = posts[j]
            if a.project_id == b.project_id:
                continue
            reasons = []
            t_sim = normalized_similarity(titles[i], titles[j], title_threshold)
            if t_sim >= title_threshold:
                reasons.append(f"похожие заголовки ({t_sim:.0%})")
            if sims is not None and a.embedding and b.embedding and sims[i, j] >= semantic_threshold:
                reasons.append(f"похожий смысл ({sims[i, j]:.0%})")
            if normalized_similarity(openings[i], openings[j], 0.8) >= 0.8:
                reasons.append("одинаковое начало")
            if not reasons:
                continue
            # the newer unpublished post is the one to rewrite
            newer, older = (a, b) if a.created_at >= b.created_at else (b, a)
            if newer.status in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value):
                newer, older = older, newer
            pairs.append({
                "rewrite": _post_brief(newer, projects), "keep": _post_brief(older, projects), "reasons": reasons,
                "can_rewrite": newer.status not in (PostStatus.PUBLISHED.value, PostStatus.PUBLISHING.value),
            })
            if len(pairs) >= limit:
                return pairs
    return pairs


def _post_brief(post: Post, projects: dict[int, Project]) -> dict:
    project = projects.get(post.project_id)
    return {"id": post.id, "project_id": post.project_id, "project": project.name if project else "",
            "title": post.title or post.topic, "status": post.status, "start": first_line(post.text)[:140]}
