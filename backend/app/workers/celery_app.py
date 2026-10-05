from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings
from app.core.logging import setup_logging

setup_logging(settings.LOG_LEVEL)

celery_app = Celery(
    "vkreger",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.tasks.publishing",
        "app.workers.tasks.maintenance",
        "app.workers.tasks.ai_jobs",
        "app.workers.tasks.inbox",
    ],
)
celery_app.conf.update(
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.publishing.*": {"queue": "publishing"},
        "app.workers.tasks.inbox.*": {"queue": "inbox"},
    },
    timezone="UTC",
    beat_schedule={
        "dispatch-due-posts": {"task": "app.workers.tasks.publishing.dispatch_due_posts", "schedule": 60.0},
        "recover-stuck-posts": {"task": "app.workers.tasks.publishing.recover_stuck_posts", "schedule": 300.0},
        "check-proxies": {"task": "app.workers.tasks.maintenance.check_all_proxies", "schedule": 15 * 60.0},
        "refresh-vk-tokens": {"task": "app.workers.tasks.maintenance.refresh_vk_tokens", "schedule": 600.0},
        "check-accounts": {"task": "app.workers.tasks.maintenance.check_all_accounts", "schedule": crontab(minute=7)},
        "collect-analytics": {"task": "app.workers.tasks.maintenance.collect_analytics", "schedule": crontab(minute=20, hour="*/3")},
        "autopilot-fill-queues": {"task": "app.workers.tasks.ai_jobs.autopilot_fill_queues", "schedule": crontab(minute=40)},
        "analyst-review": {"task": "app.workers.tasks.ai_jobs.analyst_reviews", "schedule": crontab(minute=10, hour=4)},
        "longpoll-cycle": {"task": "app.workers.tasks.inbox.longpoll_cycle", "schedule": 30.0},
        "triage-pending": {"task": "app.workers.tasks.inbox.triage_pending", "schedule": 120.0},
    },
)
