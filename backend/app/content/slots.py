"""Publication slot calculation from posting frequency and preferred times."""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.content import Post
from app.models.enums import PostStatus
from app.models.project import Project

# drafts with a planned time hold their slot while waiting for approval
ACTIVE_STATUSES = [PostStatus.DRAFT.value, PostStatus.APPROVED.value, PostStatus.SCHEDULED.value, PostStatus.PUBLISHING.value,
                   PostStatus.PUBLISHED.value]


def _parse_time(value: str) -> time | None:
    try:
        hh, mm = value.strip().split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return None


def daily_times(project: Project) -> list[time]:
    times = sorted({t for t in (_parse_time(v) for v in (project.posting_times or [])) if t})
    per_day = project.posts_per_day
    if per_day and per_day > 0:
        if len(times) >= per_day:
            # keep evenly distributed subset
            step = len(times) / per_day
            times = [times[int(i * step)] for i in range(per_day)]
        else:
            start, end = 9 * 60, 21 * 60
            spread = [start + int(i * (end - start) / max(per_day - 1, 1)) for i in range(per_day)]
            times = sorted({*times, *[time(m // 60, m % 60) for m in spread]})[:per_day]
    return times or [time(10, 0)]


def allowed_weekdays(project: Project) -> set[int]:
    if project.posts_per_day:
        return set(range(7))
    per_week = project.posts_per_week or 7
    if per_week >= 7:
        return set(range(7))
    return {round(i * 7 / per_week) % 7 for i in range(per_week)}


def tz(project: Project) -> ZoneInfo:
    try:
        return ZoneInfo(project.timezone or "UTC")
    except Exception:
        return ZoneInfo("UTC")


def free_slots(db: Session, project: Project, count: int, *, horizon_days: int = 14,
               after: datetime | None = None) -> list[datetime]:
    """Return up to ``count`` UTC datetimes not yet taken by queued/published posts."""
    zone = tz(project)
    now = after or datetime.now(UTC)
    taken_rows = db.execute(
        select(Post.scheduled_at).where(
            Post.project_id == project.id, Post.status.in_(ACTIVE_STATUSES),
            Post.scheduled_at >= now - timedelta(days=1),
        )
    ).scalars().all()
    taken = {_as_utc(t).replace(second=0, microsecond=0) for t in taken_rows if t}
    weekdays = allowed_weekdays(project)
    times = daily_times(project)
    per_day_cap = project.posts_per_day or len(times)
    if not project.posts_per_day:
        per_day_cap = max(1, -(-(project.posts_per_week or 7) // 7))
        times = times[:per_day_cap] if len(times) > per_day_cap else times
    result: list[datetime] = []
    local_today = now.astimezone(zone).date()
    for offset in range(horizon_days + 1):
        day: date = local_today + timedelta(days=offset)
        if day.weekday() not in weekdays:
            continue
        for t in times:
            slot = datetime.combine(day, t, tzinfo=zone).astimezone(UTC)
            if slot <= now + timedelta(minutes=5) or slot in taken:
                continue
            result.append(slot)
            if len(result) >= count:
                return result
    return result


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
