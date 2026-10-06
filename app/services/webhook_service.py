from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
import logging

from app.db.models import Project, WebhookEvent, AuditLog, Withdrawal, Wallet, Transaction, User
from app.core.domain_enums import ProjectStatus
from app.core.tasks import enqueue_websocket_task, enqueue_email_task


class WebhookValidationError(Exception):
    pass


class WebhookProcessingError(Exception):
    pass


logger = logging.getLogger(__name__)


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
        amount: Decimal,
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

                # Synchronize Project Budget with actual payment amount
                project.budget = amount
                
                # Update status to COMPLETED if not already
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
                            details={"from": previous, "to": ProjectStatus.COMPLETED.value, "source": provider, "budget_sync": str(amount)},
                        )
                    )
            
            # TRIGGER FINANCIAL ENGINE
            from app.tasks.financials import process_payout_calculation
            process_payout_calculation.delay(project_id=project_id)
            
        except IntegrityError:
            await db.rollback()
            logger.info("Duplicate webhook event ignored", extra={"provider": provider, "event_id": event_id})
            return

    @staticmethod
    async def process_withdrawal_payout_success(
        db: AsyncSession,
        provider: str,
        event_id: str,
        reference: str,
        payload_hash: str,
        amount: Optional[Decimal] = None,
    ) -> None:
        """
        Auto-marks a team withdrawal / payout as 'paid' upon receiving confirmation
        from Paystack Transfers, Flutterwave, or Stripe.
        """
        try:
            user_to_notify_id = None
            notified_amount = None

            async with db.begin():
                existing = await db.execute(
                    select(WebhookEvent).where(WebhookEvent.provider == provider, WebhookEvent.event_id == event_id)
                )
                if existing.scalars().first():
                    return

                # Record idempotency event
                event = WebhookEvent(
                    provider=provider,
                    event_id=event_id,
                    payload_hash=payload_hash,
                    status="processed",
                )
                db.add(event)

                # Look up matching withdrawal by reference or idempotency key
                withdrawal = None
                # First try matching exact external_payout_idempotency_key
                res = await db.execute(
                    select(Withdrawal).where(Withdrawal.external_payout_idempotency_key == reference).with_for_update()
                )
                withdrawal = res.scalars().first()

                # If not matched, try parsing withdrawal ID from reference (e.g. "withdrawal:123" or "123")
                if not withdrawal and reference:
                    clean_id_str = reference.replace("withdrawal:", "").replace("titan_payout_", "").split("_")[0]
                    if clean_id_str.isdigit():
                        res = await db.execute(
                            select(Withdrawal).where(Withdrawal.id == int(clean_id_str)).with_for_update()
                        )
                        withdrawal = res.scalars().first()

                if not withdrawal:
                    logger.warning("Withdrawal payout success event received but no matching withdrawal found", extra={"reference": reference, "provider": provider})
                    return

                user_to_notify_id = withdrawal.user_id
                notified_amount = withdrawal.amount

                if withdrawal.status != "paid":
                    previous_status = withdrawal.status
                    withdrawal.status = "paid"
                    if not withdrawal.external_payout_idempotency_key:
                        withdrawal.external_payout_idempotency_key = reference

                    db.add(
                        AuditLog(
                            actor_type="system",
                            actor_id=None,
                            action="withdrawal_payout_confirmed",
                            target_type="withdrawal",
                            target_id=withdrawal.id,
                            details={
                                "from": previous_status,
                                "to": "paid",
                                "source": provider,
                                "reference": reference,
                                "amount": str(amount or withdrawal.amount),
                            },
                        )
                    )

            # Send real-time notifications outside the transaction block
            if user_to_notify_id:
                enqueue_websocket_task(
                    user_id=user_to_notify_id,
                    message={
                        "type": "withdrawal_update",
                        "title": "Payout Disbursed 💸",
                        "message": f"Your payout of ${notified_amount} has been successfully sent to your bank via {provider.capitalize()}!",
                        "status": "paid",
                    },
                )
        except IntegrityError:
            await db.rollback()
            logger.info("Duplicate payout webhook event ignored", extra={"provider": provider, "event_id": event_id})
            return

    @staticmethod
    async def process_withdrawal_payout_failed(
        db: AsyncSession,
        provider: str,
        event_id: str,
        reference: str,
        reason: str,
        payload_hash: str,
    ) -> None:
        """
        Handles failed or reversed payouts from Paystack/Flutterwave by restoring
        escrowed funds back to the user's wallet and setting status to 'rejected'.
        """
        try:
            user_to_notify_id = None
            notified_amount = None

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
                    status="processed",
                )
                db.add(event)

                withdrawal = None
                res = await db.execute(
                    select(Withdrawal).where(Withdrawal.external_payout_idempotency_key == reference).with_for_update()
                )
                withdrawal = res.scalars().first()

                if not withdrawal and reference:
                    clean_id_str = reference.replace("withdrawal:", "").replace("titan_payout_", "").split("_")[0]
                    if clean_id_str.isdigit():
                        res = await db.execute(
                            select(Withdrawal).where(Withdrawal.id == int(clean_id_str)).with_for_update()
                        )
                        withdrawal = res.scalars().first()

                if not withdrawal:
                    logger.warning("Payout failed event received but no matching withdrawal found", extra={"reference": reference, "provider": provider})
                    return

                user_to_notify_id = withdrawal.user_id
                notified_amount = withdrawal.amount

                if withdrawal.status != "rejected":
                    # Refund funds back to the user wallet
                    wallet_res = await db.execute(
                        select(Wallet).where(Wallet.user_id == withdrawal.user_id).with_for_update()
                    )
                    user_wallet = wallet_res.scalars().first()
                    if user_wallet:
                        user_wallet.balance += withdrawal.amount
                        db.add(
                            Transaction(
                                wallet_id=user_wallet.id,
                                amount=withdrawal.amount,
                                transaction_type="credit",
                                description=f"Payout #{withdrawal.id} transfer reversed/failed ({reason}) - funds restored",
                                reference_id=f"withdrawal:reversal:{withdrawal.id}",
                            )
                        )

                    withdrawal.status = "rejected"
                    db.add(
                        AuditLog(
                            actor_type="system",
                            actor_id=None,
                            action="withdrawal_payout_failed_refunded",
                            target_type="withdrawal",
                            target_id=withdrawal.id,
                            details={"reason": reason, "provider": provider, "reference": reference},
                        )
                    )

            if user_to_notify_id:
                enqueue_websocket_task(
                    user_id=user_to_notify_id,
                    message={
                        "type": "withdrawal_update",
                        "title": "Payout Transfer Failed ❌",
                        "message": f"Your payout transfer of ${notified_amount} could not be completed ({reason}). Your funds have been restored to your wallet.",
                        "status": "rejected",
                    },
                )
        except IntegrityError:
            await db.rollback()
            logger.info("Duplicate payout failure webhook ignored", extra={"provider": provider, "event_id": event_id})
            return

    @staticmethod
    async def process_sumsub_kyc_event(
        db: AsyncSession,
        event_id: str,
        applicant_id: str,
        external_user_id: Optional[str],
        review_status: str,
        review_answer: Optional[str],
        payload_hash: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Handles Sumsub KYC verification webhooks:
        reviewAnswer == 'GREEN' -> Verified & Approved
        reviewAnswer == 'RED'   -> Requires Resubmission / Rejected
        """
        try:
            user_to_notify = None
            async with db.begin():
                existing = await db.execute(
                    select(WebhookEvent).where(WebhookEvent.provider == "sumsub", WebhookEvent.event_id == event_id)
                )
                if existing.scalars().first():
                    return

                event = WebhookEvent(
                    provider="sumsub",
                    event_id=event_id,
                    payload_hash=payload_hash,
                    status="processed",
                )
                db.add(event)

                user = None
                if external_user_id:
                    if str(external_user_id).isdigit():
                        res = await db.execute(select(User).where(User.id == int(external_user_id)).with_for_update())
                        user = res.scalars().first()
                    if not user:
                        res = await db.execute(select(User).where(User.email == str(external_user_id)).with_for_update())
                        user = res.scalars().first()

                if user:
                    user_to_notify = user.id
                    is_verified = (review_answer == "GREEN")

                    db.add(
                        AuditLog(
                            actor_type="system",
                            actor_id=None,
                            action="kyc_verification_update",
                            target_type="user",
                            target_id=user.id,
                            details={
                                "applicant_id": applicant_id,
                                "review_status": review_status,
                                "review_answer": review_answer,
                                "verified": is_verified,
                                "meta": details or {},
                            },
                        )
                    )

            if user_to_notify:
                is_approved = (review_answer == "GREEN")
                enqueue_websocket_task(
                    user_id=user_to_notify,
                    message={
                        "type": "kyc_status_update",
                        "title": "Identity Verification Approved ✅" if is_approved else "KYC Review Update ⚠️",
                        "message": "Your Sumsub KYC identity documents have been approved!" if is_approved else "Your identity documents require additional review or resubmission.",
                        "verified": is_approved,
                    },
                )
        except IntegrityError:
            await db.rollback()
            return
