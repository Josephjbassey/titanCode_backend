"""
TitanCode Technologies — Financial Background Tasks
===================================================
This module contains tasks related to the financial engine,
specifically project payout calculations and wallet updates.
"""

import logging
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.core.tasks import record_dead_letter
from app.db.database import AsyncSessionLocal
from app.db.models import Project, User, Wallet, Transaction, PayoutInvoice
from app.services.financial_integrity import ensure_transaction_recorded, reconcile_wallet_ledgers
from app.core.tasks import enqueue_email_task
from app.core.config import settings

# ── Structured JSON Logging ───────────────────────────────────────────
logger = logging.getLogger(__name__)

@celery_app.task(bind=True, name="process_payout_calculation", max_retries=5)
def process_payout_calculation(
    self,
    project_id: int,
    idempotency_key: str | None = None,
    externally_triggered: bool = False,
):
    """
    Synchronous wrapper for our asynchronous payout logic.
    
    Why this matters:
    Celery is a task queue that usually handles functions synchronously. Since our 
    database operations use 'asyncio', we need this bridge to run our async 
    code inside the synchronous Celery worker.
    """
    payload = {"project_id": project_id, "idempotency_key": idempotency_key, "externally_triggered": externally_triggered}
    try:
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                return executor.submit(
                    lambda: asyncio.run(
                        _process_payout_calculation_async(
                            project_id,
                            idempotency_key=idempotency_key,
                            externally_triggered=externally_triggered,
                        )
                    )
                ).result()

        try:
            cur_loop = asyncio.get_event_loop()
        except RuntimeError:
            cur_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(cur_loop)

        return cur_loop.run_until_complete(
            _process_payout_calculation_async(
                project_id,
                idempotency_key=idempotency_key,
                externally_triggered=externally_triggered,
            )
        )
    except Exception as exc:
        retries = int(self.request.retries)
        if retries >= int(self.max_retries):
            record_dead_letter.delay(
                failed_task=self.name,
                payload=payload,
                error_message=str(exc),
                retries=retries,
                failed_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.exception("Financial task exhausted retries", extra={"project_id": project_id})
            raise

        countdown = min(2 ** max(retries, 0), 300)
        logger.warning("Retrying financial task", extra={"project_id": project_id, "retry": retries + 1, "countdown": countdown})
        raise self.retry(exc=exc, countdown=countdown)


async def _process_payout_calculation_async(
    project_id: int,
    idempotency_key: str | None = None,
    externally_triggered: bool = False,
) -> bool:
    """
    The Core Financial Engine: Calculates how money is split when a project ends.
    
    Beginner Note:
    We use 'async with' to manage resources like database sessions automatically.
    This ensures that even if something breaks, the connection to the DB is safely closed.
    """
    if externally_triggered and not idempotency_key:
        raise ValueError("idempotency_key is required for externally triggered payouts")

    payout_key = idempotency_key or f"project:{project_id}"
    logger.info(
        "Financial Engine: Starting payout calculation for Project ID %s [key=%s]",
        project_id,
        payout_key,
    )
    
    from app.db import database as db_mod
    async with db_mod.AsyncSessionLocal() as session:
        try:
            # ATOMIC TRANSACTION: 'session.begin()' means "All these changes must happen together, or none at all."
            # If we update User A's wallet but the server crashes before User B, this rolls back User A too.
            async with session.begin():
                logger.info(f"Financial Engine: Transaction started for Project {project_id}")
                
                # 1. IDEMPOTENCY CHECK: "Don't do the same work twice."
                # We check if an invoice already exists. If it does, we stop immediately so we don't pay twice!
                stmt = select(PayoutInvoice).where(PayoutInvoice.project_id == project_id)
                result = await session.execute(stmt)
                if result.scalars().first():
                    logger.warning(f"Financial Engine: Project {project_id} was already paid. Skipping. [IDEMPOTENCY]")
                    return False
                
                # 2. FETCH DATA: Get the project and its members from the database.
                # 'selectinload' is a performance trick to fetch the list of members in one go.
                stmt = (
                    select(Project)
                    .options(selectinload(Project.members))
                    .where(Project.id == project_id)
                    .with_for_update()
                )
                result = await session.execute(stmt)
                project = result.scalars().first()
                
                if not project or project.status != "completed":
                    logger.error(f"Financial Engine: Project missing or not complete. Aborting.")
                    return False
                    
                members = project.members
                
                # 3. PROFIT SPLIT CALCULATION: Dynamic Split (3-Tier or 70/30)
                from app.api.v1.endpoints.financials import _get_active_settings
                active_settings = await _get_active_settings()
                
                m_pct = Decimal(str(active_settings.get("member_split_percent", 60.0))) / Decimal("100.0")
                o_pct = Decimal(str(active_settings.get("overhead_split_percent", 15.0))) / Decimal("100.0")

                total_member_payout = (project.budget * m_pct).quantize(Decimal("0.01"))
                total_overhead_payout = (project.budget * o_pct).quantize(Decimal("0.01"))
                company_share = project.budget - total_member_payout - total_overhead_payout
                
                if not members:
                    # If no members, the full squad share is kept by the company as backup.
                    per_member_payout = Decimal("0.00")
                else:
                    # Divide the team's share equally among all members.
                    per_member_payout = total_member_payout / Decimal(len(members))
                    # '.quantize' rounds the value to exactly 2 decimal places (cents).
                    per_member_payout = per_member_payout.quantize(Decimal("0.01"))
                    
                # 4. DISBURSEMENT: Update member wallets and record the history.
                for member in members:
                    # Find each member's personal wallet.
                    stmt = select(Wallet).where(Wallet.user_id == member.id).with_for_update()
                    res = await session.execute(stmt)
                    wallet = res.scalars().first()
                    
                    if not wallet:
                        # If they don't have a wallet yet, create one on the fly.
                        wallet = Wallet(user_id=member.id, balance=Decimal("0.00"), currency="USD")
                        session.add(wallet)
                        await session.flush() # Ensure it gets an ID before we continue.
                    
                    # Update the balance.
                    wallet.balance += per_member_payout
                    
                    # Create a TRANSACTION record: This is the 'receipt' so we can audit later.
                    transaction = Transaction(
                        wallet_id=wallet.id,
                        amount=per_member_payout,
                        transaction_type="credit",
                        description=f"Profit split for Project: {project.name}",
                        reference_id=f"{payout_key}:member:{member.id}",
                    )
                    session.add(transaction)
                    await session.flush()
                    await ensure_transaction_recorded(session, wallet_id=wallet.id, reference_id=transaction.reference_id)

                # 5. COMPANY SHARE & OVERHEAD POOL:
                # Retains Company Treasury share and Overhead pool in CompanyWallet
                company_total_payout = company_share + total_overhead_payout
                if company_total_payout > 0:
                    from app.db.models import CompanyWallet
                    stmt = select(CompanyWallet).with_for_update()
                    res = await session.execute(stmt)
                    company_wallet = res.scalars().first()
                    
                    if not company_wallet:
                        company_wallet = CompanyWallet(balance=Decimal("0.00"), currency="USD")
                        session.add(company_wallet)
                        await session.flush()
                    
                    company_wallet.balance += company_total_payout
                    logger.info(
                        f"Financial Engine: Credited Treasury=${company_share}, Non-Billable Overhead=${total_overhead_payout} to Company Treasury for Project {project_id}"
                    )

                    # Backward compatibility: sync client/owner personal wallet if present
                    if project.client_id:
                        stmt_cw = select(Wallet).where(Wallet.user_id == project.client_id).with_for_update()
                        res_cw = await session.execute(stmt_cw)
                        client_wallet = res_cw.scalars().first()
                        if client_wallet:
                            client_wallet.balance += company_total_payout

                # Audit Log of the split breakdown
                from app.db.models import AuditLog
                session.add(
                    AuditLog(
                        actor_type="system",
                        actor_id=None,
                        action="payout_split_calculated",
                        target_type="project",
                        target_id=project_id,
                        details={
                            "total_budget": str(project.budget),
                            "squad_share": str(total_member_payout),
                            "overhead_share": str(total_overhead_payout),
                            "treasury_share": str(company_share),
                            "member_count": len(members),
                            "split_model": active_settings.get("split_model", "three_tier_60_15_25"),
                        },
                    )
                )

                # 6. INVOICE GENERATION: Create a final document summarizes the whole payout.
                session.add(PayoutInvoice(
                    project_id=project.id,
                    total_payout_amount=project.budget,
                    team_payout_amount=total_member_payout,
                    company_payout_amount=company_total_payout,
                    is_approved=False
                ))
            
            # If we reached here without errors, 'session.begin()' will commit (save) all changes to the DB.
                logger.info(f"Financial Engine: Transaction committed for Project {project_id}")
            logger.info(f"Financial Engine: Success. Payout for Project {project_id} finalized.")
            return True
            
        except Exception as e:
            # If ANYTHING went wrong, the entire session is rolled back automatically.
            logger.error(f"Financial Engine: CRITICAL FAIL on Project {project_id}. Transaction rolled back.")
            raise


@celery_app.task(name="run_daily_financial_reconciliation")
def run_daily_financial_reconciliation() -> bool:
    """Daily reconciliation job for wallet balances vs transaction ledger."""
    async def _run() -> tuple[int, str]:
        async with AsyncSessionLocal() as session:
            rows = await reconcile_wallet_ledgers(session)
            mismatches = [r for r in rows if r.delta != Decimal("0.00")]
            report_lines = [
                f"wallet_id={r.wallet_id} balance={r.recorded_balance} ledger={r.ledger_balance} delta={r.delta}"
                for r in mismatches
            ]
            report = "\n".join(report_lines) if report_lines else "No mismatches detected."
            return len(mismatches), report

    mismatches, report = asyncio.run(_run())
    logger.info("Daily financial reconciliation completed", extra={"mismatch_count": mismatches})
    enqueue_email_task(
        recipient_email=str(settings.FIRST_SUPERUSER),
        subject="[TitanCode] Daily Financial Reconciliation Report",
        body=f"Mismatch count: {mismatches}\n\n{report}",
        html_content=None,
    )
    return mismatches == 0
