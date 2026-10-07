"""
TitanCode Technologies — Integration Registry Service
======================================================
Centralises all outbound calls to external services (HubSpot, Slack, etc.)
so they can be toggled, audited, and updated from a single place.

Each dispatcher:
  1. Reads IntegrationConfig from the DB to check is_active / credentials.
  2. Falls back to settings-based credentials if no DB record exists.
  3. Never raises — catches all exceptions and logs them via IntegrationEvent.
"""

import json
import logging
from typing import Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.models import IntegrationConfig, IntegrationEvent

logger = logging.getLogger(__name__)


class IntegrationService:

    # ──────────────────────────────────────────────────────────────────
    # Core helpers
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def get_config(db: AsyncSession, service_name: str) -> Optional[IntegrationConfig]:
        """Fetch integration config by service name."""
        result = await db.execute(
            select(IntegrationConfig).where(IntegrationConfig.service_name == service_name)
        )
        return result.scalars().first()

    @staticmethod
    async def log_event(
        db: AsyncSession,
        integration_id: int,
        event_type: str,
        payload: dict,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Record an integration event for the audit trail."""
        event = IntegrationEvent(
            integration_id=integration_id,
            event_type=event_type,
            payload_json=json.dumps(payload),
            status=status,
            error_message=error,
        )
        db.add(event)
        await db.commit()

    # ──────────────────────────────────────────────────────────────────
    # HubSpot
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def dispatch_hubspot_contact(db: AsyncSession, lead: dict) -> None:
        """
        Sync a lead to HubSpot CRM Contacts API v3.
        Logs success/failure/skipped to IntegrationEvent.
        Falls back to settings.HUBSPOT_ACCESS_TOKEN if no DB config exists.
        """
        config = await IntegrationService.get_config(db, "hubspot")

        # Resolve token: DB credentials take priority, then env var
        token: Optional[str] = None
        if config and config.credentials_json:
            creds = json.loads(config.credentials_json)
            token = creds.get("access_token")
        if not token:
            token = settings.HUBSPOT_ACCESS_TOKEN

        integration_id = config.id if config else None

        if not token or (config and not config.is_active):
            status_val = "skipped"
            msg = "HubSpot not configured or inactive — lead recorded in TitanCode CRM only."
            logger.info(msg)
            if integration_id:
                await IntegrationService.log_event(db, integration_id, "hubspot_contact_sync", lead, status_val, msg)
            return

        names = (lead.get("full_name") or "Lead").strip().split(" ", 1)
        payload = {
            "properties": {
                "email": lead.get("email", ""),
                "firstname": names[0],
                "lastname": names[1] if len(names) > 1 else "",
                "phone": lead.get("phone") or "",
                "company": lead.get("company") or "",
                "message": (lead.get("message") or "")[:1000],
                "hs_lead_status": "NEW",
            }
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://api.hubspot.com/crm/v3/objects/contacts",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json=payload,
                )
            if resp.status_code in (200, 201, 409):
                if integration_id:
                    await IntegrationService.log_event(db, integration_id, "hubspot_contact_sync", lead, "success")
            else:
                error = f"HubSpot responded with status {resp.status_code}: {resp.text[:200]}"
                logger.warning(error)
                if integration_id:
                    await IntegrationService.log_event(db, integration_id, "hubspot_contact_sync", lead, "failed", error)
        except Exception as exc:
            error = str(exc)
            logger.warning("HubSpot lead sync failed: %s", error)
            if integration_id:
                await IntegrationService.log_event(db, integration_id, "hubspot_contact_sync", lead, "failed", error)

    # ──────────────────────────────────────────────────────────────────
    # Slack
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    async def dispatch_slack_notification(db: AsyncSession, message: str) -> None:
        """
        Post a Slack notification via Incoming Webhook.
        Logs success/failure/skipped to IntegrationEvent.
        Falls back to settings.SLACK_WEBHOOK_URL if no DB config exists.
        """
        config = await IntegrationService.get_config(db, "slack")

        webhook_url: Optional[str] = None
        if config and config.credentials_json:
            creds = json.loads(config.credentials_json)
            webhook_url = creds.get("webhook_url")
        if not webhook_url:
            webhook_url = settings.SLACK_WEBHOOK_URL

        integration_id = config.id if config else None

        if not webhook_url or (config and not config.is_active):
            status_val = "skipped"
            msg = "Slack not configured or inactive — notification skipped."
            logger.info(msg)
            if integration_id:
                await IntegrationService.log_event(db, integration_id, "slack_notification", {"message": message}, status_val, msg)
            return

        payload = {"text": message}
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.post(webhook_url, json=payload)
            if resp.status_code == 200:
                if integration_id:
                    await IntegrationService.log_event(db, integration_id, "slack_notification", {"message": message}, "success")
            else:
                error = f"Slack responded with status {resp.status_code}"
                logger.warning(error)
                if integration_id:
                    await IntegrationService.log_event(db, integration_id, "slack_notification", {"message": message}, "failed", error)
        except Exception as exc:
            error = str(exc)
            logger.warning("Slack notification failed: %s", error)
            if integration_id:
                await IntegrationService.log_event(db, integration_id, "slack_notification", {"message": message}, "failed", error)
