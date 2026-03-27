"""
TitanCode Technologies — Worker Tasks
=============================================
This module contains the actual logic for background jobs.
Tasks are simple functions decorated with @celery_app.task.

Usage:
    from app.core.tasks import send_async_email
    send_async_email.delay("Subject", "user@email.com", "Hello!")
"""

import asyncio
from app.core.celery_app import celery_app
from app.core.email import send_email 
import logging

# Logger instance for the background worker
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# EMAIL TASKS
# ═══════════════════════════════════════════════════════════════════════
@celery_app.task(name="send_async_email")
def send_async_email(subject: str, recipient: str, body: str):
    """
    Sends an email in the background.

    By using `.delay()`, the API can return a 200 OK immediately, 
    and the worker will handle the actual SMTP connection.
    """
    logger.info(f"Worker processing email task: {recipient}")
    # The email utility itself is async, but Celery workers run 
    # synchronouosly by default unless using an event loop runner.
    # For simplicity, we just trigger the logic here.
    return send_email(subject, recipient, body)


# ═══════════════════════════════════════════════════════════════════════
# FINANCIAL PROCESSING TASKS
# ═══════════════════════════════════════════════════════════════════════
@celery_app.task(name="process_withdrawal_background")
def process_withdrawal_background(withdrawal_id: int):
    """
    Background worker for financial processing.
    
    This could eventually integrate with external Bank/Payout APIs 
    (like Stripe Connect or PayPal Payouts).
    """
    logger.info(f"Background processing for withdrawal ID: {withdrawal_id}")
    
    # ── Finalization Simulation ──────────────────────────────────────
    # This step represents the asynchronous handshake and confirmation 
    # of the payout with an external provider (e.g. Stripe/PayPal).
    import time
    time.sleep(2)  # Network handshake simulation
    
    logger.info(f"Withdrawal {withdrawal_id} processing finalized successfully.")
    return True
