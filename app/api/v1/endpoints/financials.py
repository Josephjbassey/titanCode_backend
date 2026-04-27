"""
TitanCode Technologies — Financials & Withdrawals
=====================================================
This module manages the corporate treasury (Company Wallet) and user payouts.
It implements a secure withdrawal workflow with status tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Any, List
from decimal import Decimal

from app.db.database import get_db
from app.db.models import CompanyWallet, Withdrawal, User, Wallet, PayoutInvoice, utcnow
from app.schemas.financials import (
    CompanyWallet as WalletSchema, 
    Withdrawal as WithdrawalSchema, 
    WithdrawalCreate, 
    WithdrawalAction,
    PayoutInvoice as PayoutInvoiceSchema,
    WithdrawalListResponse,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker
from app.core.tasks import enqueue_email_task, enqueue_websocket_task
from app.core.rate_limiter import limiter
from starlette.requests import Request
from sqlalchemy import func

# Create the router
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admins = RoleChecker(["CEO", "Admin"])

WITHDRAWAL_ALLOWED_TRANSITIONS = {
    "pending": {"approved", "rejected"},
    "approved": {"paid"},
    "rejected": set(),
    "paid": set(),
}


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
    result = await db.execute(
        select(Wallet).where(Wallet.user_id == current_user.id).with_for_update()
    )
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
@router.get("/withdrawals", response_model=WithdrawalListResponse)
async def list_withdrawals(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status_filter: str | None = Query(None, alias="status"),
    user_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    List withdrawal requests.
    - Admins see all requests across the platform.
    - Users see only their own requests.
    """
    filters = []
    if status_filter:
        filters.append(Withdrawal.status == status_filter)
    if current_user.role in ["CEO", "Admin"]:
        if user_id is not None:
            filters.append(Withdrawal.user_id == user_id)
    else:
        filters.append(Withdrawal.user_id == current_user.id)

    total = (await db.execute(select(func.count(Withdrawal.id)).where(*filters))).scalar_one()
    result = await db.execute(
        select(Withdrawal)
        .where(*filters)
        .order_by(Withdrawal.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    items = result.scalars().all()
    next_offset = offset + limit if offset + limit < total else None
    return {"items": items, "total": total, "limit": limit, "offset": offset, "next_offset": next_offset}


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
    result = await db.execute(
        select(Withdrawal).where(Withdrawal.id == withdrawal_id).with_for_update()
    )
    withdrawal = result.scalars().first()
    if not withdrawal:
        raise HTTPException(status_code=404, detail="Withdrawal request not found")

    current_status = withdrawal.status
    target_status = action.status

    if target_status == "paid":
        if not action.idempotency_key:
            raise HTTPException(
                status_code=400,
                detail="idempotency_key is required when status is paid",
            )
        if (
            withdrawal.external_payout_idempotency_key
            and withdrawal.external_payout_idempotency_key != action.idempotency_key
        ):
            raise HTTPException(
                status_code=409,
                detail="Withdrawal already has a different external payout idempotency key",
            )
        if not withdrawal.external_payout_idempotency_key:
            withdrawal.external_payout_idempotency_key = action.idempotency_key

    # Idempotent replay: avoid repeated side effects (refunds/notifications/email).
    if target_status == current_status:
        return withdrawal

    if target_status not in WITHDRAWAL_ALLOWED_TRANSITIONS.get(current_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Illegal withdrawal transition: {current_status} -> {target_status}",
        )

    # Handle fund restoration on rejection
    if target_status == "rejected":
        result = await db.execute(
            select(Wallet).where(Wallet.user_id == withdrawal.user_id).with_for_update()
        )
        user_wallet = result.scalars().first()
        if user_wallet:
            user_wallet.balance += withdrawal.amount

    # Update status and reviewer
    withdrawal.status = target_status
    withdrawal.reviewed_by = current_user.id
    
    await db.commit()
    await db.refresh(withdrawal)

    # Notify the user of the action taken on their withdrawal request
    notification_messages = {
        "approved": (
            "Withdrawal Approved ✅",
            f"Your withdrawal of ${withdrawal.amount} has been approved and is being processed.",
        ),
        "rejected": (
            "Withdrawal Rejected ❌",
            f"Your withdrawal of ${withdrawal.amount} was rejected. The funds have been returned to your wallet.",
        ),
        "paid": (
            "Payout Sent! 💸",
            f"Your payout of ${withdrawal.amount} has been sent. Check your bank account!",
        ),
    }

    title, message_text = notification_messages.get(
        target_status, ("Withdrawal Update", f"Your withdrawal status is now: {target_status}")
    )

    # Real-time WebSocket push
    enqueue_websocket_task(
        user_id=withdrawal.user_id,
        message={
            "type": "withdrawal_update",
            "title": title,
            "message": message_text,
            "withdrawal_id": withdrawal.id,
            "status": target_status,
        },
    )

    # Fetch user info for email
    user_result = await db.execute(select(User).where(User.id == withdrawal.user_id))
    notified_user = user_result.scalars().first()
    if notified_user and notified_user.email:
        enqueue_email_task(
            recipient_email=notified_user.email,
            subject=f"Withdrawal Update: {title}",
            body=(
                f"Hi {notified_user.full_name},\n\n"
                f"{message_text}\n\n"
                f"Amount: ${withdrawal.amount}\n"
                f"Status: {target_status.upper()}\n\n"
                f"— The TitanCode Finance Team"
            ),
            html_content=(
                f"<p>Hi <strong>{notified_user.full_name}</strong>,</p>"
                f"<p>{message_text}</p>"
                f"<table style='border-collapse:collapse;font-family:sans-serif;'>"
                f"<tr><td style='padding:6px;font-weight:bold;'>Amount</td><td style='padding:6px;'>${withdrawal.amount}</td></tr>"
                f"<tr><td style='padding:6px;font-weight:bold;'>Status</td><td style='padding:6px;'>{target_status.upper()}</td></tr>"
                f"</table>"
                f"<br><p>— The TitanCode Finance Team</p>"
            ),
        )

    return withdrawal


# ═══════════════════════════════════════════════════════════════════════
# POST /payouts/{id}/approve — Approve Project Payout (Admin)
# ═══════════════════════════════════════════════════════════════════════
@router.post("/payouts/{invoice_id}/approve", response_model=PayoutInvoiceSchema)
@limiter.limit("5/minute")
async def approve_payout(
    request: Request,
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(allow_admins),
) -> Any:
    """
    Approve an internal project payout invoice (CEO/Admin only).
    
    This is the "Safety Net" before funds are considered 'locked' 
    for bank transfer in future phases.
    
    Constraints:
    - Strictly protected by Admin RBAC.
    - Rate limited to 5 requests per minute per IP.
    """
    result = await db.execute(select(PayoutInvoice).where(PayoutInvoice.id == invoice_id))
    invoice = result.scalars().first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Payout invoice not found")
        
    if invoice.is_approved:
        raise HTTPException(status_code=400, detail="Payout invoice is already approved")

    # Flip the approval bit
    invoice.is_approved = True
    invoice.processed_at = utcnow() # From db.models
    
    await db.commit()
    await db.refresh(invoice)
    return invoice
