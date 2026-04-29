from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.models import Project, WebhookEvent, AuditLog
from app.core.domain_enums import ProjectStatus


class WebhookValidationError(Exception):
    pass


class WebhookProcessingError(Exception):
    pass


class WebhookService:
    @staticmethod
    def validate_timestamp(ts_seconds: int, max_skew_seconds: int = 300) -> None:
        now = datetime.now(timezone.utc)
        ts = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
        if abs((now - ts).total_seconds()) > max_skew_seconds:
            raise WebhookValidationError("Webhook timestamp outside allowed freshness window")

    @staticmethod
    async def process_project_payment_success(
        db: AsyncSession,
        provider: str,
        event_id: str,
        project_id: int,
        payload_hash: str,
    ) -> None:
        try:
            async with db.begin():
                existing = await db.execute(
                    select(WebhookEvent).where(WebhookEvent.provider == provider, WebhookEvent.event_id == event_id)
                )
                if existing.scalars().first():
                    return

                event = WebhookEvent(
                    provider=provider,
                    event_id=event_id,
                    payload_hash=payload_hash,
                    project_id=project_id,
                    status="processed",
                )
                db.add(event)

                result = await db.execute(select(Project).where(Project.id == project_id).with_for_update())
                project = result.scalars().first()
                if not project:
                    raise WebhookProcessingError(f"Project {project_id} not found")

                if project.status != ProjectStatus.COMPLETED.value:
                    previous = project.status
                    project.status = ProjectStatus.COMPLETED.value
                    db.add(
                        AuditLog(
                            actor_type="system",
                            actor_id=None,
                            action="project_status_transition",
                            target_type="project",
                            target_id=project_id,
                            details={"from": previous, "to": ProjectStatus.COMPLETED.value, "source": provider},
                        )
                    )
        except IntegrityError:
            # Duplicate webhook delivery under concurrency; treat as idempotent success.
            await db.rollback()
            return
