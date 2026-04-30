"""
TitanCode Technologies — Worker Tasks
=============================================
Background tasks for email delivery and websocket notifications.
These tasks are designed to avoid blocking request/response lifecycles.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from celery.exceptions import MaxRetriesExceededError

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.email import send_email
from app.core.notifications import manager as notification_manager

# Logger instance for the background worker
logger = logging.getLogger(__name__)

EMAIL_MAX_RETRIES = 5
WEBSOCKET_MAX_RETRIES = 5
MAX_RETRY_DELAY_SECONDS = 300


def _run_async(coro):
    """Run async coroutine safely from sync Celery workers."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    return loop.run_until_complete(coro)


def _retry_delay(retries: int) -> int:
    """Exponential backoff with cap."""
    return min(2 ** max(retries, 0), MAX_RETRY_DELAY_SECONDS)


@celery_app.task(name="record_dead_letter")
def record_dead_letter(
    failed_task: str,
    payload: Dict[str, Any],
    error_message: str,
    retries: int,
    failed_at: Optional[str] = None,
) -> bool:
    """Persist dead-letter context in structured logs for auditing and alert admins."""
    timestamp = failed_at or datetime.now(timezone.utc).isoformat()
    logger.error(
        "Dead-lettered task after max retries",
        extra={
            "failed_task": failed_task,
            "payload": payload,
            "error": error_message,
            "retries": retries,
            "failed_at": timestamp,
        },
    )

    admin_email = getattr(settings, "FIRST_SUPERUSER", None)
    if admin_email:
        try:
            _run_async(
                send_email(
                    recipient_email=str(admin_email),
                    subject=f"[TitanCode Alert] Dead letter task: {failed_task}",
                    body=(
                        f"Task: {failed_task}\n"
                        f"Failed at: {timestamp}\n"
                        f"Retries: {retries}\n"
                        f"Error: {error_message}\n"
                        f"Payload: {payload}"
                    ),
                    html_content=None,
                )
            )
        except Exception:
            logger.exception("Failed to send dead-letter admin alert", extra={"failed_task": failed_task})
    return True


@celery_app.task(bind=True, name="send_async_email", max_retries=EMAIL_MAX_RETRIES)
def send_async_email(
    self,
    recipient_email: str,
    subject: str,
    body: str,
    html_content: Optional[str] = None,
) -> bool:
    """Send an email with retry/backoff and dead-letter fallback."""
    payload = {
        "recipient_email": recipient_email,
        "subject": subject,
        "body": body,
        "html_content": html_content,
    }

    try:
        sent = _run_async(
            send_email(
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                html_content=html_content,
            )
        )
        if not sent:
            raise RuntimeError("Email provider returned unsuccessful status")
        logger.info("Email task completed", extra={"recipient_email": recipient_email})
        return True
    except Exception as exc:
        retry_count = int(self.request.retries)
        if retry_count >= EMAIL_MAX_RETRIES:
            record_dead_letter.delay(
                failed_task=self.name,
                payload=payload,
                error_message=str(exc),
                retries=retry_count,
            )
            logger.exception("Email task exhausted retries", extra={"recipient_email": recipient_email})
            return False

        delay_seconds = _retry_delay(retry_count)
        logger.warning(
            "Retrying email task",
            extra={
                "recipient_email": recipient_email,
                "retry": retry_count + 1,
                "countdown_seconds": delay_seconds,
            },
        )
        try:
            raise self.retry(exc=exc, countdown=delay_seconds)
        except MaxRetriesExceededError:
            record_dead_letter.delay(
                failed_task=self.name,
                payload=payload,
                error_message=str(exc),
                retries=retry_count,
            )
            logger.exception("Email task failed with MaxRetriesExceededError")
            return False


@celery_app.task(bind=True, name="send_websocket_notification", max_retries=WEBSOCKET_MAX_RETRIES)
def send_websocket_notification(self, user_id: int, message: Dict[str, Any]) -> bool:
    """Dispatch websocket messages asynchronously with retry/backoff."""
    payload = {"user_id": user_id, "message": message}
    try:
        _run_async(notification_manager.send_personal_message(user_id=user_id, message=message))
        logger.info("Websocket notification task completed", extra={"user_id": user_id})
        return True
    except Exception as exc:
        retry_count = int(self.request.retries)
        if retry_count >= WEBSOCKET_MAX_RETRIES:
            record_dead_letter.delay(
                failed_task=self.name,
                payload=payload,
                error_message=str(exc),
                retries=retry_count,
            )
            logger.exception("Websocket task exhausted retries", extra={"user_id": user_id})
            return False

        delay_seconds = _retry_delay(retry_count)
        logger.warning(
            "Retrying websocket notification task",
            extra={
                "user_id": user_id,
                "retry": retry_count + 1,
                "countdown_seconds": delay_seconds,
            },
        )
        try:
            raise self.retry(exc=exc, countdown=delay_seconds)
        except MaxRetriesExceededError:
            record_dead_letter.delay(
                failed_task=self.name,
                payload=payload,
                error_message=str(exc),
                retries=retry_count,
            )
            logger.exception("Websocket task failed with MaxRetriesExceededError")
            return False


@celery_app.task(name="process_withdrawal_background")
def process_withdrawal_background(withdrawal_id: int):
    """Placeholder financial background task."""
    logger.info(f"Background processing for withdrawal ID: {withdrawal_id}")
    import time
    time.sleep(2)
    logger.info(f"Withdrawal {withdrawal_id} processing finalized successfully.")
    return True


def enqueue_email_task(
    recipient_email: str,
    subject: str,
    body: str,
    html_content: Optional[str] = None,
) -> None:
    """Enqueue email task without blocking API responses."""
    try:
        send_async_email.delay(
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            html_content=html_content,
        )
    except Exception:
        logger.exception(
            "Failed to enqueue email task",
            extra={"recipient_email": recipient_email, "subject": subject},
        )


def enqueue_websocket_task(user_id: int, message: Dict[str, Any]) -> None:
    """Enqueue websocket task without blocking API responses."""
    try:
        send_websocket_notification.delay(user_id=user_id, message=message)
    except Exception:
        logger.exception("Failed to enqueue websocket task", extra={"user_id": user_id})
