"""
TitanCode Technologies — Financial Background Tasks
===================================================
This module contains tasks related to the financial engine,
specifically project payout calculations and wallet updates.
"""

import logging
import asyncio
from decimal import Decimal
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.core.celery_app import celery_app
from app.db.database import AsyncSessionLocal
from app.db.models import Project, User, Wallet, Transaction, PayoutInvoice

# ── Structured JSON Logging ───────────────────────────────────────────
logger = logging.getLogger(__name__)

@celery_app.task(name="process_payout_calculation")
def process_payout_calculation(
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
    try:
        # Step 1: Get the current 'brain' (event loop) of the process.
        loop = asyncio.get_event_loop()
    except RuntimeError:
        # Step 2: If no brain is active, create a new one.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # Step 3: If the brain is already thinking (running), safely schedule our task.
        return asyncio.run_coroutine_threadsafe(
            _process_payout_calculation_async(
                project_id,
                idempotency_key=idempotency_key,
                externally_triggered=externally_triggered,
            ),
            loop,
        ).result()
    else:
        # Step 4: Otherwise, run our async task until it finishes.
        return loop.run_until_complete(
            _process_payout_calculation_async(
                project_id,
                idempotency_key=idempotency_key,
                externally_triggered=externally_triggered,
            )
        )


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
    
    async with AsyncSessionLocal() as session:
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
                )
                result = await session.execute(stmt)
                project = result.scalars().first()
                
                if not project or project.status != "completed":
                    logger.error(f"Financial Engine: Project missing or not complete. Aborting.")
                    return False
                    
                members = project.members
                
                # 3. PROFIT SPLIT CALCULATION: (70% to Team, 30% to Company)
                # We use 'Decimal' instead of 'float' because floats are imprecise for money (e.g., 0.1 + 0.2 != 0.3).
                total_member_payout = project.budget * Decimal("0.70")
                
                if not members:
                    # If no members, the full 70% share is kept by the company as backup.
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

                # 5. COMPANY SHARE: The remaining 30% goes to the client/company wallet.
                company_share = project.budget - total_member_payout
                if company_share > 0:
                    stmt = select(Wallet).where(Wallet.user_id == project.client_id).with_for_update()
                    res = await session.execute(stmt)
                    company_wallet = res.scalars().first()
                    
                    if not company_wallet:
                        company_wallet = Wallet(user_id=project.client_id, balance=Decimal("0.00"), currency="USD")
                        session.add(company_wallet)
                        await session.flush()
                    
                    company_wallet.balance += company_share
                    session.add(Transaction(
                        wallet_id=company_wallet.id, amount=company_share,
                        transaction_type="credit", description=f"Company profit share (30%)",
                        reference_id=f"{payout_key}:company:{project.client_id}",
                    ))

                # 6. INVOICE GENERATION: Create a final document summarizes the whole payout.
                session.add(PayoutInvoice(
                    project_id=project.id,
                    total_payout_amount=project.budget,
                    team_payout_amount=total_member_payout,
                    company_payout_amount=company_share,
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
