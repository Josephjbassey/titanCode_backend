import hmac
import hashlib
import logging
import json
from decimal import Decimal
from fastapi import APIRouter, Request, Header, HTTPException, Depends
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.database import get_db
from app.db.models import ClientInvoice
from app.core.rate_limiter import limiter
from app.schemas.webhooks import (
    PaystackWebhookEnvelope,
    FlutterwaveWebhookEnvelope,
    SumsubWebhookEnvelope,
    StripeWebhookEnvelope,
)
from app.services.webhook_service import WebhookService, WebhookValidationError, WebhookProcessingError

router = APIRouter()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# PAYSTACK WEBHOOK (Incoming Client Charges & Outgoing Staff Transfers)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/paystack")
@limiter.limit("30/minute")
async def paystack_webhook(
    request: Request,
    x_paystack_signature: str = Header(None),
    x_paystack_event_id: str = Header(None),
    x_paystack_timestamp: str = Header(None),
    db_session: AsyncSession = Depends(get_db),
):
    if not x_paystack_signature:
        logger.warning("Rejected paystack webhook: missing x-paystack-signature")
        raise HTTPException(status_code=400, detail="Missing x-paystack-signature header")

    payload = await request.body()
    secret = settings.PAYSTACK_SECRET_KEY or ""
    if not secret:
        logger.error("Rejected paystack webhook: secret not configured")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")

    expected_hmac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected_hmac, x_paystack_signature):
        logger.warning("Rejected paystack webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_id = x_paystack_event_id or hashlib.sha256(payload).hexdigest()[:32]
    payload_hash = hashlib.sha256(payload).hexdigest()

    if x_paystack_timestamp:
        try:
            ts = int(x_paystack_timestamp)
            WebhookService.validate_timestamp(ts)
        except (ValueError, OverflowError):
            logger.warning("Rejected paystack webhook: invalid timestamp header")
            raise HTTPException(status_code=400, detail="Invalid timestamp header")
        except WebhookValidationError as exc:
            logger.warning("Rejected paystack webhook: replay/stale timestamp", extra={"event_id": event_id})
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = PaystackWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    data = event.data or {}

    # 1. Incoming Client Payment Succeeded
    if event.event == "charge.success":
        meta = data.get("metadata") or {}
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                # Paystack amounts are in kobo (base unit * 100)
                raw_amount = data.get("amount", 0)
                amount_decimal = Decimal(str(raw_amount)) / 100

                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="paystack",
                    event_id=event_id,
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
                        invoice.provider_reference = event_id
                        await db_session.commit()
            except WebhookProcessingError as exc:
                logger.error("Paystack charge processing failed", extra={"event_id": event_id, "error": str(exc)})
                raise HTTPException(status_code=422, detail=str(exc))

    # 2. Outgoing Staff Payout / Transfer Completed Successfully
    elif event.event == "transfer.success":
        reference = data.get("reference") or data.get("transfer_code")
        raw_amount = data.get("amount", 0)
        amount_decimal = Decimal(str(raw_amount)) / 100 if raw_amount else None
        if reference:
            await WebhookService.process_withdrawal_payout_success(
                db=db_session,
                provider="paystack",
                event_id=event_id,
                reference=reference,
                payload_hash=payload_hash,
                amount=amount_decimal,
            )

    # 3. Outgoing Staff Payout / Transfer Failed or Reversed
    elif event.event in ("transfer.failed", "transfer.reversed"):
        reference = data.get("reference") or data.get("transfer_code")
        reason = data.get("reason") or data.get("gateway_response") or "Transfer failed at gateway"
        if reference:
            await WebhookService.process_withdrawal_payout_failed(
                db=db_session,
                provider="paystack",
                event_id=event_id,
                reference=reference,
                reason=reason,
                payload_hash=payload_hash,
            )

    return {"status": "success"}


# ═══════════════════════════════════════════════════════════════════════
# FLUTTERWAVE WEBHOOK (Incoming Client Charges & Outgoing Disbursals)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/flutterwave")
@limiter.limit("30/minute")
async def flutterwave_webhook(
    request: Request,
    verif_hash: str = Header(None),
    x_flutterwave_signature: str = Header(None),
    x_flutterwave_event_id: str = Header(None),
    x_flutterwave_timestamp: str = Header(None),
    db_session: AsyncSession = Depends(get_db),
):
    expected_secret = getattr(settings, "FLUTTERWAVE_WEBHOOK_SECRET", None) or settings.FLUTTERWAVE_SECRET_KEY
    if not expected_secret:
        logger.error("Rejected flutterwave webhook: secret not configured")
        raise HTTPException(status_code=500, detail="Webhook secret is not configured")

    payload = await request.body()
    signature = x_flutterwave_signature or verif_hash

    # Flutterwave supports both simple secret hash header comparison and HMAC-SHA256
    expected_hmac = hmac.new(expected_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    if not signature or (signature != expected_secret and not hmac.compare_digest(signature, expected_hmac)):
        logger.warning("Rejected flutterwave webhook: invalid signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    event_id = x_flutterwave_event_id or hashlib.sha256(payload).hexdigest()[:32]
    payload_hash = hashlib.sha256(payload).hexdigest()

    if x_flutterwave_timestamp:
        try:
            ts = int(x_flutterwave_timestamp)
            WebhookService.validate_timestamp(ts)
        except (ValueError, OverflowError):
            logger.warning("Rejected flutterwave webhook: invalid timestamp header")
            raise HTTPException(status_code=400, detail="Invalid timestamp header")
        except WebhookValidationError as exc:
            logger.warning("Rejected flutterwave webhook: replay/stale timestamp", extra={"event_id": event_id})
            raise HTTPException(status_code=400, detail=str(exc))

    try:
        event = FlutterwaveWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")

    data = event.data or {}

    # 1. Incoming Client Payment Succeeded
    if event.event == "charge.completed" and data.get("status") == "successful":
        meta = data.get("meta") or {}
        project_id_str = meta.get("project_id")
        if project_id_str:
            try:
                raw_amount = data.get("amount", 0)
                amount_decimal = Decimal(str(raw_amount))

                await WebhookService.process_project_payment_success(
                    db=db_session,
                    provider="flutterwave",
                    event_id=event_id,
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
                        invoice.provider_reference = event_id
                        await db_session.commit()
            except WebhookProcessingError as exc:
                logger.error("Flutterwave webhook processing failed", extra={"event_id": event_id, "error": str(exc)})
                raise HTTPException(status_code=422, detail=str(exc))

    # 2. Outgoing Staff Transfer Succeeded
    elif event.event == "transfer.completed" and data.get("status") == "SUCCESSFUL":
        reference = data.get("reference")
        raw_amount = data.get("amount", 0)
        amount_decimal = Decimal(str(raw_amount)) if raw_amount else None
        if reference:
            await WebhookService.process_withdrawal_payout_success(
                db=db_session,
                provider="flutterwave",
                event_id=event_id,
                reference=reference,
                payload_hash=payload_hash,
                amount=amount_decimal,
            )

    # 3. Outgoing Staff Transfer Failed
    elif event.event == "transfer.completed" and data.get("status") == "FAILED":
        reference = data.get("reference")
        reason = data.get("complete_message") or "Disbursal transfer failed at bank"
        if reference:
            await WebhookService.process_withdrawal_payout_failed(
                db=db_session,
                provider="flutterwave",
                event_id=event_id,
                reference=reference,
                reason=reason,
                payload_hash=payload_hash,
            )

    return {"status": "success"}


# ═══════════════════════════════════════════════════════════════════════
# SUMSUB KYC IDENTITY VERIFICATION WEBHOOK
# ═══════════════════════════════════════════════════════════════════════
@router.post("/sumsub")
@limiter.limit("30/minute")
async def sumsub_webhook(
    request: Request,
    x_payload_digest: str = Header(None),
    x_payload_digest_alg: str = Header("HMAC_SHA256_HEX"),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Receives automated KYC applicant review events from Sumsub:
    - applicantReviewed (GREEN = approved, RED = rejected)
    - applicantPending
    - applicantCreated
    """
    secret = settings.SUMSUB_WEBHOOK_SECRET or settings.SUMSUB_SECRET_KEY or ""
    payload = await request.body()

    if secret and x_payload_digest:
        # Sumsub signature is HMAC-SHA256 (or HMAC-SHA1/SHA512 based on header)
        digest_maker = hashlib.sha256 if "256" in x_payload_digest_alg else hashlib.sha512
        expected_digest = hmac.new(secret.encode("utf-8"), payload, digest_maker).hexdigest()
        if not hmac.compare_digest(expected_digest, x_payload_digest):
            logger.warning("Rejected Sumsub webhook: invalid HMAC signature")
            raise HTTPException(status_code=400, detail="Invalid Sumsub signature")

    try:
        event = SumsubWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid Sumsub payload")

    event_id = hashlib.sha256(payload).hexdigest()[:32]
    payload_hash = hashlib.sha256(payload).hexdigest()

    review_result = event.reviewResult or {}
    review_answer = review_result.get("reviewAnswer")  # "GREEN" or "RED"
    review_status = event.reviewStatus or "pending"

    await WebhookService.process_sumsub_kyc_event(
        db=db_session,
        event_id=event_id,
        applicant_id=event.applicantId or "unknown",
        external_user_id=event.externalUserId,
        review_status=review_status,
        review_answer=review_answer,
        payload_hash=payload_hash,
        details=review_result,
    )

    return {"status": "success"}


# ═══════════════════════════════════════════════════════════════════════
# STRIPE WEBHOOK (Production / Future Multi-Currency Expansion)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/stripe")
@limiter.limit("30/minute")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db_session: AsyncSession = Depends(get_db),
):
    secret = settings.STRIPE_WEBHOOK_SECRET
    payload = await request.body()

    if secret and stripe_signature:
        # Basic signature timestamp check and signature validation
        sig_parts = dict(item.split("=") for item in stripe_signature.split(",") if "=" in item)
        timestamp = sig_parts.get("t")
        v1_sig = sig_parts.get("v1")
        if timestamp and v1_sig:
            signed_payload = f"{timestamp}.".encode("utf-8") + payload
            expected_mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected_mac, v1_sig):
                logger.warning("Rejected Stripe webhook: signature mismatch")
                raise HTTPException(status_code=400, detail="Invalid Stripe signature")

    try:
        event = StripeWebhookEnvelope.model_validate_json(payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid Stripe payload")

    event_id = event.id or hashlib.sha256(payload).hexdigest()[:32]
    payload_hash = hashlib.sha256(payload).hexdigest()
    data_obj = (event.data or {}).get("object") or {}

    if event.type in ("checkout.session.completed", "payment_intent.succeeded"):
        meta = data_obj.get("metadata") or {}
        project_id_str = meta.get("project_id")
        if project_id_str:
            raw_amount = data_obj.get("amount") or data_obj.get("amount_received") or 0
            amount_decimal = Decimal(str(raw_amount)) / 100
            await WebhookService.process_project_payment_success(
                db=db_session,
                provider="stripe",
                event_id=event_id,
                project_id=int(project_id_str),
                amount=amount_decimal,
                payload_hash=payload_hash,
            )

    elif event.type in ("transfer.paid", "payout.paid"):
        reference = data_obj.get("transfer_group") or data_obj.get("id")
        if reference:
            await WebhookService.process_withdrawal_payout_success(
                db=db_session,
                provider="stripe",
                event_id=event_id,
                reference=reference,
                payload_hash=payload_hash,
            )

    return {"status": "success"}
