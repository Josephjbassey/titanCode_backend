import hmac
import hashlib
import logging
import json
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from app.core.rate_limiter import limiter
from app.schemas.webhooks import PaystackWebhookEnvelope, FlutterwaveWebhookEnvelope
from app.services.webhook_service import WebhookService, WebhookValidationError, WebhookProcessingError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/paystack")
@limiter.limit("10/minute")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
    x_paystack_event_id: str = Header(None),
    x_paystack_timestamp: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    if not x_paystack_signature or not x_paystack_event_id or not x_paystack_timestamp:
        raise HTTPException(status_code=400, detail="Missing required webhook headers")

    payload = await request.body()
    secret = settings.PAYSTACK_SECRET_KEY or ""
    if not secret:
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")
    expected_hmac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected_hmac, x_paystack_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        ts = int(x_paystack_timestamp)
        WebhookService.validate_timestamp(ts)
    except (ValueError, OverflowError):
        raise HTTPException(status_code=400, detail="Invalid timestamp header")
    except WebhookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = PaystackWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    if event.event == "charge.success":
        meta = event.data.get("metadata", {})
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                payload_hash = hashlib.sha256(payload).hexdigest()
                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="paystack",
                    event_id=x_paystack_event_id,
                    project_id=int(project_id_str),
                    payload_hash=payload_hash,
                )
            except WebhookProcessingError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "success"}


@router.post("/flutterwave")
@limiter.limit("10/minute")
async def flutterwave_webhook(
    request: Request,
    verif_hash: str = Header(None),
    x_flutterwave_event_id: str = Header(None),
    x_flutterwave_timestamp: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    expected_hash = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", None) or settings.FLUTTERWAVE_SECRET_KEY
    if not verif_hash or not expected_hash or not hmac.compare_digest(verif_hash, expected_hash):
        raise HTTPException(status_code=401, detail="Invalid signature")
    if not x_flutterwave_event_id or not x_flutterwave_timestamp:
        raise HTTPException(status_code=400, detail="Missing required webhook headers")

    try:
        ts = int(x_flutterwave_timestamp)
        WebhookService.validate_timestamp(ts)
    except (ValueError, OverflowError):
        raise HTTPException(status_code=400, detail="Invalid timestamp header")
    except WebhookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    payload = await request.body()
    try:
        event = FlutterwaveWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    if event.event == "charge.completed" and event.data.get("status") == "successful":
        meta = event.data.get("meta", {})
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="flutterwave",
                    event_id=x_flutterwave_event_id,
                    project_id=int(project_id_str),
                    payload_hash=hashlib.sha256(payload).hexdigest(),
                )
            except WebhookProcessingError as exc:
                raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "success"}
