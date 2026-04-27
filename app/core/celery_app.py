"""
TitanCode Technologies — Celery Worker Configuration
=====================================================
Celery is used for background execution of side effects so API requests
can return quickly and reliably.
"""

from celery import Celery

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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="default",
    task_create_missing_queues=True,
    task_routes={
        "record_dead_letter": {"queue": "dead_letter"},
        "send_async_email": {"queue": "notifications"},
        "send_websocket_notification": {"queue": "notifications"},
    },
    # Helps prevent lost tasks during worker crashes/restarts.
    broker_transport_options={"visibility_timeout": 3600},
)
