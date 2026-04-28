import logging
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Project

logger = logging.getLogger(__name__)

class PaymentService:
    @staticmethod
    async def process_successful_payment(project_id: int, db_session: AsyncSession) -> None:
        """
        Common handler logic for when money hits the merchant account.
        """
        try:
            async with db_session.begin():
                stmt = select(Project).where(Project.id == project_id).with_for_update()
                result = await db_session.execute(stmt)
                project = result.scalars().first()

                if not project:
                    logger.error(f"Webhook Execution: Project {project_id} not found.")
                    return

                if project.status == "completed":
                    logger.info(f"Webhook Execution: Project {project_id} already processed. Skipping.")
                    return

                project.status = "completed"
                logger.info(f"Webhook Execution: Payment Verified. Updating Project {project_id} to completed.")

            # Handoff to Celery background task (DEFERRED for Phase 1 MVP)
            # process_payout_calculation.delay(project_id)
            # logger.info(f"Webhook Execution: Success. Payout task dispatched for Project {project_id}.")
        except Exception as e:
            logger.error(f"Failed to handle successful payment: {str(e)}")
