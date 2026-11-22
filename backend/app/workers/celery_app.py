"""The Celery application: background jobs run by a worker process.

    celery -A app.workers.celery_app worker --loglevel=info   # runs jobs (Windows: --pool=solo)
    celery -A app.workers.celery_app beat --loglevel=info     # puts scheduled jobs on the queue

Redis is the broker (the queue). We don't store task results: jobs write what matters to
Postgres themselves.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("gatesense", broker=settings.redis_url, include=["app.workers.tasks"])
celery_app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,  # a job is removed from the queue only after it finishes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    broker_connection_retry_on_startup=True,
)

# Times are UTC: 21:30 UTC = 03:00 in India, when the gate is quietest.
celery_app.conf.beat_schedule = {
    "escalation-every-minute": {"task": "escalation.tick", "schedule": 60.0},
    "notifications-every-minute": {"task": "notifications.dispatch", "schedule": 60.0},
    "reconciliation-nightly": {
        "task": "reconciliation.nightly",
        "schedule": crontab(hour=21, minute=30),
    },
    "retention-daily": {"task": "retention.daily", "schedule": crontab(hour=22, minute=0)},
}
