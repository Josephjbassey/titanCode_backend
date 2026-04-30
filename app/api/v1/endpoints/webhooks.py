import hmac
import hashlib
import logging
import json
from decimal import Decimal
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.db.database import get_db
from sqlalchemy.future import select
from app.db.models import ClientInvoice
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
        logger.warning("Rejected paystack webhook: missing headers")
        raise HTTPException(status_code=400, detail="Missing required webhook headers")

    payload = await request.body()
    secret = settings.PAYSTACK_SECRET_KEY or ""
    if not secret:
        logger.error("Rejected paystack webhook: secret not configured")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")
    expected_hmac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected_hmac, x_paystack_signature):
        logger.warning("Rejected paystack webhook: invalid signature", extra={"event_id": x_paystack_event_id})
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        ts = int(x_paystack_timestamp)
        WebhookService.validate_timestamp(ts)
    except (ValueError, OverflowError):
        logger.warning("Rejected paystack webhook: invalid timestamp header")
        raise HTTPException(status_code=400, detail="Invalid timestamp header")
    except WebhookValidationError as exc:
        logger.warning("Rejected paystack webhook: replay/stale timestamp", extra={"event_id": x_paystack_event_id})
        logger.warning("Rejected flutterwave webhook: invalid timestamp header")
        raise HTTPException(status_code=400, detail="Invalid timestamp header")
    except WebhookValidationError as exc:
        logger.warning("Rejected flutterwave webhook: replay/stale timestamp", extra={"event_id": x_flutterwave_event_id})
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = PaystackWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    if event.event == "charge.success":
        meta = event.data.get("metadata") or {}
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                payload_hash = hashlib.sha256(payload).hexdigest()
                # Paystack amounts are in kobo (base unit * 100)
                raw_amount = event.data.get("amount", 0)
                amount_decimal = Decimal(str(raw_amount)) / 100
                
                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="paystack",
                    event_id=x_paystack_event_id,
                    project_id=int(project_id_str),
                    amount=amount_decimal,
                    payload_hash=payload_hash,
                )
                invoice_id = meta.get("invoice_id")
                if invoice_id:
                    invoice = (
                        await db_session.execute(
                            select(ClientInvoice).where(ClientInvoice.invoice_id == invoice_id)
                        )
                    ).scalars().first()
                    if invoice:
                        invoice.status = "paid"
                        invoice.provider_reference = x_paystack_event_id
                        await db_session.commit()
            except WebhookProcessingError as exc:
                logger.error("Paystack webhook processing failed", extra={"event_id": x_paystack_event_id, "error": str(exc)})
                logger.error("Flutterwave webhook processing failed", extra={"event_id": x_flutterwave_event_id, "error": str(exc)})
                raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "success"}


@router.post("/flutterwave")
@limiter.limit("10/minute")
async def flutterwave_webhook(
    request: Request,
    verif_hash: str = Header(None),
    x_flutterwave_signature: str = Header(None),
    x_flutterwave_event_id: str = Header(None),
    x_flutterwave_timestamp: str = Header(None),
    db_session: AsyncSession = Depends(get_db)
):
    expected_secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", None) or settings.FLUTTERWAVE_SECRET_KEY
    if not expected_secret:
        logger.error("Rejected flutterwave webhook: secret not configured")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")
    if not x_flutterwave_event_id or not x_flutterwave_timestamp:
        logger.warning("Rejected flutterwave webhook: missing headers")
        raise HTTPException(status_code=400, detail="Missing required webhook headers")

    try:
        ts = int(x_flutterwave_timestamp)
        WebhookService.validate_timestamp(ts)
    except (ValueError, OverflowError):
        logger.warning("Rejected flutterwave webhook: invalid timestamp header")
        logger.warning("Rejected paystack webhook: invalid timestamp header")
        raise HTTPException(status_code=400, detail="Invalid timestamp header")
    except WebhookValidationError as exc:
        logger.warning("Rejected flutterwave webhook: replay/stale timestamp", extra={"event_id": x_flutterwave_event_id})
        raise HTTPException(status_code=400, detail=str(exc))

    payload = await request.body()
    expected_hmac = hmac.new(expected_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    signature = x_flutterwave_signature or verif_hash
    if not signature or not hmac.compare_digest(signature, expected_hmac):
        logger.warning("Rejected flutterwave webhook: invalid signature", extra={"event_id": x_flutterwave_event_id})
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        event = FlutterwaveWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    if event.event == "charge.completed" and event.data.get("status") == "successful":
        meta = event.data.get("meta") or {}
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                # Flutterwave amounts are in the currency's major unit
                raw_amount = event.data.get("amount", 0)
                amount_decimal = Decimal(str(raw_amount))
                
                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="flutterwave",
                    event_id=x_flutterwave_event_id,
                    project_id=int(project_id_str),
                    amount=amount_decimal,
                    payload_hash=hashlib.sha256(payload).hexdigest(),
                )
                invoice_id = meta.get("invoice_id")
                if invoice_id:
                    invoice = (
                        await db_session.execute(
                            select(ClientInvoice).where(ClientInvoice.invoice_id == invoice_id)
                        )
                    ).scalars().first()
                    if invoice:
                        invoice.status = "paid"
                        invoice.provider_reference = x_flutterwave_event_id
                        await db_session.commit()
            except WebhookProcessingError as exc:
                logger.error("Flutterwave webhook processing failed", extra={"event_id": x_flutterwave_event_id, "error": str(exc)})
                raise HTTPException(status_code=422, detail=str(exc))

    return {"status": "success"}
