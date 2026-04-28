import hmac
import hashlib
import logging
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from app.db.models import Project
from app.core.rate_limiter import limiter
from app.services.payment_service import PaymentService

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/paystack")
@limiter.limit("10/minute")
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
            await PaymentService.process_successful_payment(int(project_id_str), db_session)
        else:
            logger.warning("Paystack webhook received without project_id metadata.")

    return {"status": "success"}

@router.post("/flutterwave")
@limiter.limit("10/minute")
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
            await PaymentService.process_successful_payment(int(project_id_str), db_session)
        else:
            logger.warning("Flutterwave webhook received without project_id metadata.")

    return {"status": "success"}
