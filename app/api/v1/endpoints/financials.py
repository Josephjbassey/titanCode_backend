"""
TitanCode Technologies — Financials & Withdrawals
=====================================================
This module manages the corporate treasury (Company Wallet) and user payouts.
It implements a secure withdrawal workflow with status tracking.
"""

import json
import uuid
import logging
import httpx
from decimal import Decimal
from contextlib import nullcontext
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.database import get_db
from app.db.models import CompanyWallet, Withdrawal, User, Wallet, PayoutInvoice, Transaction, Project, AuditLog, utcnow
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

logger = logging.getLogger(__name__)

# Backward-compatibility alias for test patchers
send_email = enqueue_email_task
from app.core.notifications import manager as notification_manager

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


@router.get("/dashboard/operations")
async def operations_dashboard(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admins),
) -> Any:
    pending_withdrawals = (
        await db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.status == "pending"))
    ).scalar_one()
    approved_withdrawals = (
        await db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.status == "approved"))
    ).scalar_one()
    paid_withdrawals = (
        await db.execute(select(func.count(Withdrawal.id)).where(Withdrawal.status == "paid"))
    ).scalar_one()
    completed_projects = (
        await db.execute(select(func.count(Project.id)).where(Project.status == "completed"))
    ).scalar_one()
    pending_projects = (
        await db.execute(select(func.count(Project.id)).where(Project.status == "pending"))
    ).scalar_one()
    active_projects = (
        await db.execute(select(func.count(Project.id)).where(Project.status == "active"))
    ).scalar_one()
    return {
        "projects": {"pending": pending_projects, "active": active_projects, "completed": completed_projects},
        "withdrawals": {
            "pending": pending_withdrawals,
            "approved": approved_withdrawals,
            "paid": paid_withdrawals,
        },
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
    bank_info = withdrawal_in.bank_info or current_user.bank_account_number
    if not bank_info:
        raise HTTPException(status_code=400, detail="Bank info is required before requesting withdrawal")
    if withdrawal_in.amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be greater than zero")

    tx_ctx = nullcontext() if db.in_transaction() else db.begin()
    async with tx_ctx:
        result = await db.execute(
            select(Wallet).where(Wallet.user_id == current_user.id).with_for_update()
        )
        user_wallet = result.scalars().first()
        if not user_wallet or user_wallet.balance < withdrawal_in.amount:
            raise HTTPException(status_code=400, detail="Insufficient funds in your personal wallet")

        withdrawal = Withdrawal(
            user_id=current_user.id,
            amount=withdrawal_in.amount,
            bank_info=bank_info,
            status="pending"
        )
        db.add(withdrawal)
        user_wallet.balance -= withdrawal_in.amount
        db.add(
            Transaction(
                wallet_id=user_wallet.id,
                amount=withdrawal_in.amount,
                transaction_type="debit",
                description=f"Withdrawal request #{current_user.id} (pending)",
                reference_id=f"withdrawal:pending:user:{current_user.id}:{utcnow().isoformat()}",
            )
        )
    if db.in_transaction():
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
    target_status = action.status or (
        {"approve": "approved", "reject": "rejected", "pay": "paid"}.get(action.action, action.action)
        if action.action else None
    )
    if not target_status:
        raise HTTPException(status_code=400, detail="Missing withdrawal action or status")

    if target_status == "paid":
        payout_key = action.idempotency_key or f"paystack:transfer:{withdrawal.id}:{uuid.uuid4().hex[:12]}"
        if (
            withdrawal.external_payout_idempotency_key
            and withdrawal.external_payout_idempotency_key != payout_key
        ):
            raise HTTPException(
                status_code=409,
                detail="Withdrawal already has a different external payout idempotency key",
            )
        if not withdrawal.external_payout_idempotency_key:
            withdrawal.external_payout_idempotency_key = payout_key

        # Connect Paystack Transfers API when configured
        if settings.PAYSTACK_SECRET_KEY and not settings.PAYSTACK_SECRET_KEY.startswith("sk_live_placeholder"):
            try:
                amount_kobo = int(Decimal(str(withdrawal.amount)) * 100)
                async with httpx.AsyncClient(timeout=10.0) as client:
                    paystack_res = await client.post(
                        "https://api.paystack.co/transfer",
                        headers={
                            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "source": "balance",
                            "amount": amount_kobo,
                            "recipient": withdrawal.bank_info or "RCP_corporate_withdrawal",
                            "reason": f"TitanCode payout #{withdrawal.id}",
                            "reference": withdrawal.external_payout_idempotency_key,
                        },
                    )
                    logger.info("Paystack transfer initiated", extra={"status": paystack_res.status_code, "withdrawal_id": withdrawal.id})
            except Exception as exc:
                logger.warning("Paystack transfer request error", extra={"error": str(exc), "withdrawal_id": withdrawal.id})

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
            db.add(
                Transaction(
                    wallet_id=user_wallet.id,
                    amount=withdrawal.amount,
                    transaction_type="credit",
                    description=f"Withdrawal #{withdrawal.id} rejected - funds restored",
                    reference_id=f"withdrawal:refund:{withdrawal.id}",
                )
            )

    # Update status and reviewer
    withdrawal.status = target_status
    withdrawal.reviewed_by = current_user.id
    
    # Audit log entry for tracking
    db.add(
        AuditLog(
            actor_type="admin",
            actor_id=current_user.id,
            action=f"withdrawal_{target_status}",
            target_type="withdrawal",
            target_id=withdrawal.id,
            details={
                "amount": str(withdrawal.amount),
                "idempotency_key": withdrawal.external_payout_idempotency_key,
                "provider": "paystack",
            },
        )
    )

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


# ═══════════════════════════════════════════════════════════════════════
# SYSTEM SETTINGS & SALARY PROFIT SPLIT LOGIC
# ═══════════════════════════════════════════════════════════════════════

class PricingTierModel(BaseModel):
    id: str
    label: str
    min_amount: float
    max_amount: float | None = None
    description: str = ""
    is_active: bool = True


class FinancialSettingsModel(BaseModel):
    company_name: str = "TitanCode Technologies Inc."
    support_email: str = "support@titancode.agency"
    currency: str = "USD"
    timezone: str = "UTC"
    split_model: str = "three_tier_60_15_25"  # "standard_70_30" | "three_tier_60_15_25" | "custom"
    platform_split_percent: float = 25.0
    overhead_split_percent: float = 15.0
    member_split_percent: float = 60.0
    notify_on_milestone: bool = True
    notify_on_withdrawal: bool = True
    pricing_tiers: List[PricingTierModel] = []


class SalaryProjectionResponse(BaseModel):
    total_budget: float
    split_model: str = "three_tier_60_15_25"
    platform_split_percent: float
    overhead_split_percent: float = 15.0
    member_split_percent: float
    platform_treasury_share: float
    overhead_pool_share: float = 0.0
    team_pool_share: float
    member_count: int
    projected_salary_per_member: float


_DEFAULT_PRICING_TIERS = [
    {"id": "tier-1", "label": "Starter", "min_amount": 10000, "max_amount": 20000, "description": "Rapid MVP — Core features, 1-2 month delivery", "is_active": True},
    {"id": "tier-2", "label": "Standard", "min_amount": 20000, "max_amount": 40000, "description": "Full product — API integrations, admin panel, 2-3 month delivery", "is_active": True},
    {"id": "tier-3", "label": "Professional", "min_amount": 40000, "max_amount": 75000, "description": "Scale-ready — Multi-tenant, advanced analytics, 3-6 month delivery", "is_active": True},
    {"id": "tier-4", "label": "Enterprise", "min_amount": 75000, "max_amount": None, "description": "Custom — Dedicated team, SLA, compliance, ongoing support", "is_active": True},
]

_DEFAULT_SETTINGS = {
    "company_name": "TitanCode Technologies Inc.",
    "support_email": "support@titancode.agency",
    "currency": "USD",
    "timezone": "UTC",
    "split_model": "three_tier_60_15_25",
    "platform_split_percent": 25.0,
    "overhead_split_percent": 15.0,
    "member_split_percent": 60.0,
    "notify_on_milestone": True,
    "notify_on_withdrawal": True,
    "pricing_tiers": _DEFAULT_PRICING_TIERS,
}
_SETTINGS_CACHE = dict(_DEFAULT_SETTINGS)
SETTINGS_REDIS_KEY = "titancode:financial_settings"


async def _get_active_settings() -> dict:
    try:
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = await redis.get(SETTINGS_REDIS_KEY)
        await redis.close()
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return dict(_SETTINGS_CACHE)


@router.get("/settings", response_model=FinancialSettingsModel)
async def get_financial_settings(
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get current global agency settings including profit split percentages.
    Available to all authenticated members.
    """
    data = await _get_active_settings()
    return FinancialSettingsModel(**data)


@router.put("/settings", response_model=FinancialSettingsModel)
async def update_financial_settings(
    payload: FinancialSettingsModel,
    _current_user: User = Depends(allow_admins),
) -> Any:
    """
    Update global agency and profit split settings. Restricted to CEO/Admin.
    Enforces that platform_split_percent + overhead_split_percent + member_split_percent equals 100%.
    """
    total_split = payload.platform_split_percent + payload.overhead_split_percent + payload.member_split_percent
    if abs(total_split - 100.0) > 0.01:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Profit split percentages must total 100%. Got {total_split:.2f}% (Platform Treasury: {payload.platform_split_percent}%, Non-Billable Overhead: {payload.overhead_split_percent}%, Squad Pool: {payload.member_split_percent}%)",
        )

    updated_dict = payload.model_dump()
    _SETTINGS_CACHE.update(updated_dict)

    try:
        redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis.set(SETTINGS_REDIS_KEY, json.dumps(updated_dict))
        await redis.close()
    except Exception:
        pass

    return payload


@router.get("/salary-projection", response_model=SalaryProjectionResponse)
async def calculate_salary_projection(
    budget: float = Query(..., ge=0, description="Total project budget in USD/currency units"),
    member_count: int = Query(1, ge=1, description="Number of participating team members"),
    split_model: str | None = Query(None, description="Active split model (standard_70_30 or three_tier_60_15_25)"),
    platform_split_percent: float | None = Query(None, ge=0, le=100),
    overhead_split_percent: float | None = Query(None, ge=0, le=100),
    member_split_percent: float | None = Query(None, ge=0, le=100),
    _current_user: User = Depends(get_current_user),
) -> Any:
    """
    Calculate salary and treasury projections based on project budget and profit split logic.
    Supports both 3-Tier (60% Squad / 15% Overhead / 25% Treasury) and Standard 70/30 distribution.
    """
    active_settings = await _get_active_settings()
    active_model = split_model or active_settings.get("split_model", "three_tier_60_15_25")

    if platform_split_percent is not None and member_split_percent is not None:
        p_split = platform_split_percent
        m_split = member_split_percent
        o_split = overhead_split_percent if overhead_split_percent is not None else max(0.0, 100.0 - p_split - m_split)
    elif active_model == "standard_70_30":
        p_split = 30.0
        o_split = 0.0
        m_split = 70.0
    else:
        # three_tier_60_15_25 default
        p_split = float(active_settings.get("platform_split_percent", 25.0))
        o_split = float(active_settings.get("overhead_split_percent", 15.0))
        m_split = float(active_settings.get("member_split_percent", 60.0))

    platform_share = round((budget * p_split) / 100.0, 2)
    overhead_share = round((budget * o_split) / 100.0, 2)
    team_share = round((budget * m_split) / 100.0, 2)
    per_member = round(team_share / member_count, 2) if member_count > 0 else 0.0

    return SalaryProjectionResponse(
        total_budget=round(budget, 2),
        split_model=active_model,
        platform_split_percent=round(p_split, 2),
        overhead_split_percent=round(o_split, 2),
        member_split_percent=round(m_split, 2),
        platform_treasury_share=platform_share,
        overhead_pool_share=overhead_share,
        team_pool_share=team_share,
        member_count=member_count,
        projected_salary_per_member=per_member,
    )

