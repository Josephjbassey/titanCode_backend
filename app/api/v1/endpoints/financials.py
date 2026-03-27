"""
TitanCode Technologies — Financials & Withdrawals
=====================================================
This module manages the corporate treasury (Company Wallet) and user payouts.
It implements a secure withdrawal workflow with status tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List
from decimal import Decimal

from app.db.database import get_db
from app.db.models import CompanyWallet, Withdrawal, User, Wallet
from app.schemas.financials import CompanyWallet as WalletSchema, Withdrawal as WithdrawalSchema, WithdrawalCreate, WithdrawalAction
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create the router
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admins = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# GET /financials/company-wallet — View Corporate Treasury
# ═══════════════════════════════════════════════════════════════════════
@router.get("/company-wallet", response_model=WalletSchema)
async def get_company_wallet(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admins),
) -> Any:
    """
    Retrieve the current balance of the global company treasury.
    Accessible only to CEO and Admin roles.
    """
    result = await db.execute(select(CompanyWallet))
    wallet = result.scalars().first()
    if not wallet:
        # Bootstrap the wallet if it doesn't exist yet
        wallet = CompanyWallet(balance=Decimal("0.00"))
        db.add(wallet)
        await db.commit()
        await db.refresh(wallet)
    return wallet


# ═══════════════════════════════════════════════════════════════════════
# POST /financials/withdrawals/request — Request Payout
# ═══════════════════════════════════════════════════════════════════════
@router.post("/withdrawals/request", response_model=WithdrawalSchema, status_code=status.HTTP_201_CREATED)
async def request_withdrawal(
    withdrawal_in: WithdrawalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Request a payout of earned funds to an external bank account.

    Workflow Logic:
    1. Verify user has enough balance in their personal wallet.
    2. Immediately deduct the requested amount (escrow/hold).
    3. Create a `pending` withdrawal record for admin review.

    Args:
        withdrawal_in: Amount and optional custom bank info.

    Returns:
        WithdrawalSchema: The created request.
    """
    # 1. Check user's personal wallet balance
    result = await db.execute(select(Wallet).where(Wallet.user_id == current_user.id))
    user_wallet = result.scalars().first()
    
    if not user_wallet or user_wallet.balance < withdrawal_in.amount:
        raise HTTPException(status_code=400, detail="Insufficient funds in your personal wallet")

    # 2. Create the withdrawal record
    withdrawal = Withdrawal(
        user_id=current_user.id,
        amount=withdrawal_in.amount,
        bank_info=withdrawal_in.bank_info or current_user.bank_account_number,
        status="pending"
    )
    db.add(withdrawal)
    
    # 3. Deduct from user wallet to prevent double-spending while pending
    user_wallet.balance -= withdrawal_in.amount
    
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal


# ═══════════════════════════════════════════════════════════════════════
# GET /financials/withdrawals — View Requests
# ═══════════════════════════════════════════════════════════════════════
@router.get("/withdrawals", response_model=List[WithdrawalSchema])
async def list_withdrawals(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List withdrawal requests.
    - Admins see all requests across the platform.
    - Users see only their own requests.
    """
    if current_user.role in ["CEO", "Admin"]:
        result = await db.execute(select(Withdrawal).order_by(Withdrawal.created_at.desc()))
    else:
        result = await db.execute(select(Withdrawal).where(Withdrawal.user_id == current_user.id).order_by(Withdrawal.created_at.desc()))
    return result.scalars().all()


# ═══════════════════════════════════════════════════════════════════════
# POST /financials/withdrawals/{id}/action — Approve/Reject (Admin)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/withdrawals/{withdrawal_id}/action", response_model=WithdrawalSchema)
async def process_withdrawal(
    withdrawal_id: int,
    action: WithdrawalAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_admins),
) -> Any:
    """
    Change the status of a withdrawal request (Admin only).

    If the request is `rejected`, the system automatically returns the 
    escrowed funds to the user's personal wallet.

    Args:
        withdrawal_id: ID of the payout request.
        action: New status (approved | rejected | paid).

    Returns:
        WithdrawalSchema: The updated request record.
    """
    result = await db.execute(select(Withdrawal).where(Withdrawal.id == withdrawal_id))
    withdrawal = result.scalars().first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")

    # Handle fund restoration on rejection
    if action.status == "rejected" and withdrawal.status != "rejected":
        result = await db.execute(select(Wallet).where(Wallet.user_id == withdrawal.user_id))
        user_wallet = result.scalars().first()
        if user_wallet:
            user_wallet.balance += withdrawal.amount

    # Update status and reviewer
    withdrawal.status = action.status
    withdrawal.reviewed_by = current_user.id
    
    await db.commit()
    await db.refresh(withdrawal)
    return withdrawal
