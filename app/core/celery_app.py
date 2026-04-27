"""
TitanCode Technologies — Celery Worker Configuration
=====================================================
Celery is used for background execution of side effects so API requests
can return quickly and reliably.
"""

from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery(
    "titancode_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.core.tasks", "app.tasks.financials"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    # Notification tasks are user-visible and non-idempotent; avoid late ACK
    # redelivery that can duplicate emails/websocket pushes.
    task_acks_late=False,
    task_reject_on_worker_lost=False,
    task_default_queue="default",
    task_create_missing_queues=False,
    task_queues=(
        Queue("default"),
        Queue("notifications"),
        Queue("dead_letter"),
    ),
    task_routes={
        "record_dead_letter": {"queue": "dead_letter"},
        "send_async_email": {"queue": "notifications"},
        "send_websocket_notification": {"queue": "notifications"},
    },
    broker_transport_options={"visibility_timeout": 3600},
)
