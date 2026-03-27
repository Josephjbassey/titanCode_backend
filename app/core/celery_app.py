"""
TitanCode Technologies — Celery Worker Configuration
=====================================================
Celery is used for running "background tasks"—long-running code 
that doesn't need to block the user API response.

This file sets up the Celery application and its connection to Redis.
"""

from celery import Celery
from app.core.config import settings

# ── Celery App Definition ─────────────────────────────────────────────
# broker:   The "post office" (Redis) where messages are sent.
# backend:  The storage (Redis) for results/status of tasks.
# include:  A list of modules where Celery should look for tasks.
celery_app = Celery(
    "titancode_worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.core.tasks"]
)

# ── Hardening & Best Practices ────────────────────────────────────────
# We use standard JSON serialization for safety and compatibility.
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # Automatically retry if Redis goes down temporarily on startup
    broker_connection_retry_on_startup=True
)
