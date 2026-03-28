import logging
import stripe
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Project
from app.tasks.financials import process_payout_calculation

router = APIRouter()
logger = logging.getLogger(__name__)

# Configure Stripe API Key globally for this module
stripe.api_key = settings.STRIPE_API_KEY

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    """
    TitanCode Financial Engine: Phase 2 — Stripe Webhook.
    
    This endpoint automates project completion and payout triggering
    based on successful client payments via Stripe.
    """
    if not stripe_signature:
        logger.warning("Stripe Webhook: Missing 'Stripe-Signature' header. Rejecting.")
        raise HTTPException(status_code=400, detail="Missing signature header")

    # 1. THE STRIPE RAW BODY TRAP
    # We must use request.body() for signature verification.
    payload = await request.body()
    
    try:
        # Verify the event using the raw payload and webhook secret
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
        logger.info(f"Stripe Webhook Verified: Event ID {event['id']}, Type {event['type']}")
    except ValueError as e:
        logger.error(f"Stripe Webhook: Invalid payload - {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Stripe Webhook Security: Signature verification failed - {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. EVENT HANDLING: Listen for successful payments
    if event["type"] in ["checkout.session.completed", "payment_intent.succeeded"]:
        session_obj = event["data"]["object"]
        metadata = session_obj.get("metadata", {})
        project_id_str = metadata.get("project_id")

        if not project_id_str:
            logger.warning(f"Stripe Webhook: No 'project_id' in metadata for session {session_obj.get('id')}")
            return {"status": "ignored", "reason": "missing_project_id_in_metadata"}

        try:
            project_id = int(project_id_str)
        except ValueError:
            logger.error(f"Stripe Webhook: Metadata 'project_id' is not an integer: {project_id_str}")
            return {"status": "error", "reason": "invalid_project_id_format"}

        # 3. ABSOLUTE IDEMPOTENCY & ATOMIC HANDOFF
        # Use the injected db_session.
        async with db_session.begin(): # Atomic Transaction Block
            # Fetch project with row lock to prevent race conditions if multiple webhooks arrive
            stmt = select(Project).where(Project.id == project_id).with_for_update()
            result = await db_session.execute(stmt)
            project = result.scalars().first()

            if not project:
                logger.error(f"Stripe Webhook: Project {project_id} not found in database.")
                return {"status": "error", "reason": "project_not_found"}

            # IDEMPOTENCY CHECK: If already completed/paid, do nothing.
            if project.status == "completed":
                logger.info(f"Stripe Webhook: Project {project_id} is already COMPLETED. Skipping duplicate task dispatch.")
                return {"status": "success", "info": "already_processed"}

            # Update Status
            logger.info(f"Stripe Webhook: Payment Verified for Project {project_id}. Updating status to 'completed'.")
            project.status = "completed"

        # 4. DISPATCH THE CELERY PAYOUT TASK
        # We do this AFTER the successful DB commit to ensure the task sees the updated status.
        process_payout_calculation.delay(project_id)
        logger.info(f"Stripe Webhook: Handoff Success. Celery payout task dispatched for Project {project_id}.")

    return {"status": "success"}
