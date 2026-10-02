from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class ProxyScheme(StrEnum):
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"


class ProxyStatus(StrEnum):
    UNKNOWN = "unknown"
    ALIVE = "alive"
    DEAD = "dead"


class AccountStatus(StrEnum):
    NEW = "new"
    ACTIVE = "active"
    INVALID = "invalid"  # token revoked/expired
    ERROR = "error"  # temporary problem (network, proxy, flood control)
    DISABLED = "disabled"


class ProjectGoal(StrEnum):
    LEADS = "leads"
    SALES = "sales"
    REACH = "reach"
    EXPERTISE = "expertise"
    TRAFFIC = "traffic"


class Tone(StrEnum):
    EXPERT = "expert"
    SIMPLE = "simple"
    SELLING = "selling"
    FRIENDLY = "friendly"
    CUSTOM = "custom"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ANALYZING = "analyzing"
    PROPOSAL_READY = "proposal_ready"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class PostStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ImageFormat(StrEnum):
    NONE = "none"
    SQUARE = "square"
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


class PlanItemStatus(StrEnum):
    PLANNED = "planned"
    USED = "used"
    SKIPPED = "skipped"


class EventMode(StrEnum):
    NONE = "none"
    CALLBACK = "callback"
    LONGPOLL = "longpoll"


class InboxKind(StrEnum):
    COMMENT = "comment"
    MESSAGE = "message"


class InboxClass(StrEnum):
    QUESTION = "QUESTION"
    LEAD = "LEAD"
    NEGATIVE = "NEGATIVE"
    SPAM = "SPAM"
    OTHER = "OTHER"


class ReplyStatus(StrEnum):
    NEW = "new"  # not processed by AI yet
    TRIAGING = "triaging"  # claimed by a worker, AI classification in progress
    SUGGESTED = "suggested"  # AI prepared a reply, shown only (OFF mode)
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SENT = "sent"
    REJECTED = "rejected"
    IGNORED = "ignored"
    FAILED = "failed"


class AutoReplyMode(StrEnum):
    OFF = "OFF"
    APPROVAL = "APPROVAL"
    AUTO = "AUTO"


class LeadStatus(StrEnum):
    NEW = "new"
    IN_PROGRESS = "in_progress"
    WON = "won"
    LOST = "lost"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class LogLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
