import hmac
import hashlib
import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Project
# from app.tasks.financials import process_payout_calculation # Deferred for Phase 1

router = APIRouter()
logger = logging.getLogger(__name__)

async def handle_successful_payment(project_id: int, db_session: AsyncSession):
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

@router.post("/paystack")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    """
    Automated Project Payout Trigger: Listens for Paystack specific events.
    """
    if not x_paystack_signature:
        logger.warning("Paystack Webhook: Missing 'x-paystack-signature' header. Rejecting.")
        raise HTTPException(status_code=400, detail="Missing signature header")

    payload = await request.body()
    secret = settings.PAYSTACK_SECRET_KEY or ""
    
    expected_hmac = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha512
    ).hexdigest()

    if expected_hmac != x_paystack_signature:
        logger.error("Paystack Webhook Security: Signature verification failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event = await request.json()
    
    if event.get("event") == "charge.success":
        # Meta dictionary sent during checkout initialization
        meta = event.get("data", {}).get("metadata", {})
        project_id_str = meta.get("project_id")
        
        if project_id_str:
            await handle_successful_payment(int(project_id_str), db_session)
        else:
            logger.warning("Paystack webhook received without project_id metadata.")

    return {"status": "success"}

@router.post("/flutterwave")
async def flutterwave_webhook(
    request: Request,
    verif_hash: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    """
    Automated Project Payout Trigger: Listens for Flutterwave specific events.
    """
    # Verify the secret hash set in the Flutterwave developer dashboard
    expected_hash = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", None) or settings.FLUTTERWAVE_SECRET_KEY
    
    if not verif_hash or verif_hash != expected_hash:
        logger.error("Flutterwave Webhook Security: Hash verification failed")
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event = await request.json()
    
    if event.get("event") == "charge.completed" and event.get("data", {}).get("status") == "successful":
        meta = event.get("data", {}).get("meta", {})
        project_id_str = meta.get("project_id")
        
        if project_id_str:
            await handle_successful_payment(int(project_id_str), db_session)
        else:
            logger.warning("Flutterwave webhook received without project_id metadata.")

    return {"status": "success"}
