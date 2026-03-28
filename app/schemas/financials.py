"""
TitanCode Technologies — Pydantic Schemas: Financials
=====================================================
This module defines schemas for managing the corporate treasury (Company Wallet)
and user withdrawal requests.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal

# ═══════════════════════════════════════════════════════════════════════
# COMPANY WALLET SCHEMAS
# ═══════════════════════════════════════════════════════════════════════

class CompanyWalletBase(BaseModel):
    """Fields for the global company treasury wallet."""
    balance: Decimal = Field(default=Decimal("0.00"), decimal_places=2)

class CompanyWallet(CompanyWalletBase):
    """The public representation of the company treasury."""
    id: int
    updated_at: datetime

    model_config = {"from_attributes": True}

# ═══════════════════════════════════════════════════════════════════════
# WITHDRAWAL SCHEMAS
# ═══════════════════════════════════════════════════════════════════════

class WithdrawalBase(BaseModel):
    """Base fields for a user withdrawal request."""
    amount: Decimal = Field(..., gt=0, decimal_places=2)
    bank_info: Optional[str] = Field(None, description="Custom bank details for this transfer")

class WithdrawalCreate(WithdrawalBase):
    """Schema for a user to request a payout (POST /financials/withdrawals/request)."""
    pass

class WithdrawalAction(BaseModel):
    """Schema for an Admin to update a withdrawal status (approve/reject/pay)."""
    status: str = Field(..., pattern="^(approved|rejected|paid)$")

class Withdrawal(WithdrawalBase):
    """Final representation of a withdrawal record."""
    id: int
    user_id: int
    status: str             # pending | approved | rejected | paid
    reviewed_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ═══════════════════════════════════════════════════════════════════════
# PAYOUT INVOICE SCHEMAS
# ═══════════════════════════════════════════════════════════════════════

class PayoutInvoiceBase(BaseModel):
    """Fields for an internal project payout invoice."""
    project_id: int
    total_payout_amount: Decimal = Field(..., decimal_places=2)

class PayoutInvoiceCreate(PayoutInvoiceBase):
    """Schema for background task to create an invoice."""
    pass

class PayoutInvoice(PayoutInvoiceBase):
    """The public representation of a payout invoice."""
    id: int
    is_approved: bool
    processed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}
