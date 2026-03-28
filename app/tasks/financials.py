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
def process_payout_calculation(project_id: int):
    """
    Synchronous wrapper for the async payout calculation logic.
    Used by Celery workers.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        # If the loop is already running (e.g. in tests), we return the coroutine
        # and let the caller await it, or we use a separate thread.
        # However, for Celery workers, it won't be running.
        # For tests, we can call the async version directly.
        return asyncio.run_coroutine_threadsafe(_process_payout_calculation_async(project_id), loop).result()
    else:
        return loop.run_until_complete(_process_payout_calculation_async(project_id))


async def _process_payout_calculation_async(project_id: int) -> bool:
    """
    Enterprise-grade payout calculation with strict idempotency,
    atomic transactions, and detailed audit logging.
    """
    logger.info(f"Financial Engine: Starting payout calculation for Project ID {project_id}")
    
    async with AsyncSessionLocal() as session:
        # 4. Atomic Transaction Block (Constraint #3)
        # Using session.begin() ensures all-or-nothing consistency.
        # We start the transaction before the first read to ensure consistency.
        try:
            async with session.begin():
                # 1. Idempotency Check (Constraint #2)
                stmt = select(PayoutInvoice).where(PayoutInvoice.project_id == project_id)
                result = await session.execute(stmt)
                if result.scalars().first():
                    logger.warning(
                        f"Financial Engine: Payout Invoice already exists for Project {project_id}. "
                        "Aborting to prevent double-funding the team. [IDEMPOTENCY_ABORT]"
                    )
                    return False
                
                # 2. Fetch Project & Members
                stmt = (
                    select(Project)
                    .options(selectinload(Project.members))
                    .where(Project.id == project_id)
                )
                result = await session.execute(stmt)
                project = result.scalars().first()
                
                if not project:
                    logger.error(f"Financial Engine: Project {project_id} not found in database. [ERROR]")
                    return False
                    
                if project.status != "completed":
                    logger.error(
                        f"Financial Engine: Project {project_id} is in status '{project.status}', "
                        "not 'completed'. Payouts are only calculated for finished work. [ERROR]"
                    )
                    return False
                    
                members = project.members
                
                # 3. Calculate Math Split (70% Members, 30% Company) (Constraint #1)
                total_member_payout = project.budget * Decimal("0.70")
                
                if not members:
                    logger.info(
                        f"Financial Engine: No members assigned to Project {project_id}. "
                        "70% split remains in company operations. [AUDIT]"
                    )
                    per_member_payout = Decimal("0.00")
                else:
                    per_member_payout = total_member_payout / Decimal(len(members))
                    per_member_payout = per_member_payout.quantize(Decimal("0.01"))
                    
                    logger.info(
                        f"Financial Engine: Profit split calculated. "
                        f"Total Budget: {project.budget}, Member Share (70%): {total_member_payout}, "
                        f"Per Member ({len(members)}): {per_member_payout} [AUDIT]"
                    )

                # Process each member's wallet credit
                for member in members:
                    stmt = select(Wallet).where(Wallet.user_id == member.id)
                    res = await session.execute(stmt)
                    wallet = res.scalars().first()
                    
                    if not wallet:
                        logger.warning(f"Financial Engine: User {member.id} missing wallet. Creating new USD wallet. [AUDIT]")
                        wallet = Wallet(user_id=member.id, balance=Decimal("0.00"), currency="USD")
                        session.add(wallet)
                        await session.flush()
                    
                    wallet.balance += per_member_payout
                    
                    transaction = Transaction(
                        wallet_id=wallet.id,
                        amount=per_member_payout,
                        transaction_type="credit",
                        description=f"Automated profit split for Project: {project.name}",
                        reference_id=str(project.id)
                    )
                    session.add(transaction)
                    logger.debug(f"Financial Engine: Prepared credit for Wallet {wallet.id} (User {member.id})")

                # 5. Credit Company Share (30%)
                company_share = project.budget - total_member_payout
                if company_share > 0:
                    stmt = select(Wallet).where(Wallet.user_id == project.client_id)
                    res = await session.execute(stmt)
                    company_wallet = res.scalars().first()
                    
                    if not company_wallet:
                        company_wallet = Wallet(user_id=project.client_id, balance=Decimal("0.00"), currency="USD")
                        session.add(company_wallet)
                        await session.flush()
                    
                    company_wallet.balance += company_share
                    
                    company_tx = Transaction(
                        wallet_id=company_wallet.id,
                        amount=company_share,
                        transaction_type="credit",
                        description=f"Company profit share (30%) for Project: {project.name}",
                        reference_id=str(project.id)
                    )
                    session.add(company_tx)
                    logger.info(f"Financial Engine: Credited Company Share ({company_share}) to Wallet {company_wallet.id}")

                # Generate the frozen PayoutInvoice record
                invoice = PayoutInvoice(
                    project_id=project.id,
                    total_payout_amount=project.budget,
                    team_payout_amount=total_member_payout,
                    company_payout_amount=company_share,
                    is_approved=False
                )
                session.add(invoice)
            
            logger.info(f"Financial Engine: DB Commit Success. Payout for Project {project_id} locked. [SUCCESS]")
            return True
            
        except Exception as e:
            logger.error(
                f"Financial Engine: CRITICAL FAIL on Project {project_id}. "
                f"Transaction rolling back. Error: {str(e)} [ROLLBACK]"
            )
            # Rollback is automatic with `async with session.begin()` on exception,
            # but we re-raise for visibility.
            raise
