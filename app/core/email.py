"""
TitanCode Technologies — Production Email Utility
=====================================================
Direct SMTP implementation using aiosmtplib for non-blocking
email delivery in FastAPI.
"""

import logging
from typing import List, Optional
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import aiosmtplib

from app.core.config import settings

# Logger for tracking email events
logger = logging.getLogger(__name__)

async def send_email(
    recipient_email: str,
    subject: str,
    body: str,
    html_content: Optional[str] = None
) -> bool:
    """
    Send an email via SMTP.
    If no SMTP_HOST is configured, it falls back to logging (for development).
    """
    # ── Fallback ────────────────────────────────────────────────────────
    if not settings.SMTP_HOST:
        logger.info(f"📧 [LOCAL-RELAY] To: {recipient_email} | Subject: {subject} (Mode: Simulated)")
        return True

    # ── MIME Message Creation ───────────────────────────────────────────
    message = MIMEMultipart("alternative")
    message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
    message["To"] = recipient_email
    message["Subject"] = subject

    # Plain text version
    part1 = MIMEText(body, "plain")
    message.attach(part1)

    # Optional HTML version
    if html_content:
        part2 = MIMEText(html_content, "html")
        message.attach(part2)

    # ── Asynchronous SMTP Delivery ──────────────────────────────────────
    try:
        smtp_options = {
            "hostname": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
            "use_tls": settings.SMTP_TLS,
        }
        
        # Start connection
        async with aiosmtplib.SMTP(**smtp_options) as smtp:
            # Login if credentials are provided
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                await smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            
            # Send the email
            await smtp.send_message(message)
            
        logger.info(f"✅ Email sent successfully to {recipient_email}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to send email to {recipient_email}: {str(e)}")
        # In production, you might want to retry via background job
        return False

async def broadcast_email(
    recipient_emails: List[str],
    subject: str,
    body: str,
    html_content: Optional[str] = None
) -> None:
    """Send the same email to multiple recipients in parallel."""
    import asyncio
    tasks = [send_email(email, subject, body, html_content) for email in recipient_emails]
    await asyncio.gather(*tasks)
