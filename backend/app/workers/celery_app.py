"""The Celery application: background jobs run by a worker process.

    celery -A app.workers.celery_app worker --loglevel=info
    # on Windows add:  --pool=solo

Redis is the broker (the queue). We don't store task results: jobs write what matters to
Postgres themselves.
"""

from celery import Celery

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
