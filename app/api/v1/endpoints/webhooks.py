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
    Automated Project Payout Trigger: Listens for Stripe Payment events.
    
    Beginner Guide:
    When a customer pays on Stripe, Stripe sends a 'Webhook' (an HTTP POST request) 
    to this endpoint to tell us "Hey, the money is here!".
    """
    if not stripe_signature:
        logger.warning("Stripe Webhook: Missing 'Stripe-Signature' header. Rejecting.")
        raise HTTPException(status_code=400, detail="Missing signature header")

    # 1. THE STRIPE RAW BODY TRAP
    # We MUST use the raw, unedited bytes from the request for security.
    # If we parse it as JSON first, the cryptographic signature won't match!
    payload = await request.body()
    
    try:
        # Verify that this request ACTUALLY came from Stripe and hasn't been tampered with.
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
        logger.info(f"Stripe Webhook Verified: Event ID {event['id']}, Type {event['type']}")
    except ValueError as e:
        # The payload was formatted incorrectly.
        logger.error(f"Stripe Webhook: Invalid payload - {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        # Someone is trying to spoof a payment! This is a security rejection.
        logger.error(f"Stripe Webhook Security: Signature verification failed - {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. EVENT HANDLING: What do we do with the verified message?
    if event["type"] in ["checkout.session.completed", "payment_intent.succeeded"]:
        session_obj = event["data"]["object"]
        # Metadata is a 'custom fields' dictionary we attached when creating the session on Stripe.
        metadata = session_obj.get("metadata", {})
        project_id_str = metadata.get("project_id")

        if not project_id_str:
            logger.warning(f"Stripe Webhook: No 'project_id' in metadata. Ignoring.")
            return {"status": "ignored", "reason": "missing_project_id_in_metadata"}

        try:
            project_id = int(project_id_str)
        except ValueError:
            logger.error(f"Stripe Webhook: Metadata 'project_id' is not an integer: {project_id_str}")
            return {"status": "error", "reason": "invalid_project_id_format"}

        # 3. IDEMPOTENCY & STATUS UPDATE
        # We wrap this in a transaction to ensure we don't accidentally update twice.
        async with db_session.begin():
            # 'with_for_update' locks this row so no other request can touch it until we are done.
            stmt = select(Project).where(Project.id == project_id).with_for_update()
            result = await db_session.execute(stmt)
            project = result.scalars().first()

            if not project:
                logger.error(f"Stripe Webhook: Project {project_id} not found.")
                return {"status": "error", "reason": "project_not_found"}

            # IDEMPOTENCY: If the project is already marked 'completed', we've already handled this.
            if project.status == "completed":
                logger.info(f"Stripe Webhook: Project {project_id} already processed. Skipping.")
                return {"status": "success", "info": "already_processed"}

            # Success! Mark the project as finished.
            logger.info(f"Stripe Webhook: Payment Verified. Updating Project {project_id} to 'completed'.")
            project.status = "completed"

        # 4. HANDOFF TO BACKGROUND TASK
        # We successfully saved the change. Now, let the Payout Engine handle the money splitting
        # on its own time so the Stripe request can finish quickly.
        process_payout_calculation.delay(project_id)
        logger.info(f"Stripe Webhook: Success. Celery payout task dispatched for Project {project_id}.")

    return {"status": "success"}
