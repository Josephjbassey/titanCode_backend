"""
TitanCode Technologies — Celery Worker Configuration
=====================================================
Celery is used for background execution of side effects so API requests
can return quickly and reliably.
"""

import ssl
from celery import Celery
from kombu import Queue

from app.core.config import settings

_redis_url = str(settings.REDIS_URL)
if _redis_url.startswith("rediss://") and "ssl_cert_reqs" not in _redis_url:
    _sep = "&" if "?" in _redis_url else "?"
    _redis_url = f"{_redis_url}{_sep}ssl_cert_reqs=CERT_NONE"

celery_app = Celery(
    "titancode_worker",
    broker=_redis_url,
    backend=_redis_url,
    include=["app.core.tasks", "app.tasks.financials"],
)

_ssl_conf = {"ssl_cert_reqs": ssl.CERT_NONE} if "rediss://" in str(settings.REDIS_URL) else None

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    broker_use_ssl=_ssl_conf,
    redis_backend_use_ssl=_ssl_conf,
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
    beat_schedule={
        "daily-financial-reconciliation": {
            "task": "run_daily_financial_reconciliation",
            "schedule": 86400.0,
            "options": {"queue": "default"},
        }
    },
)
