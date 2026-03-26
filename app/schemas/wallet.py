"""
TitanCode Technologies — Pydantic Schemas: Wallet & Transaction
================================================================
Schemas for the wallet/payment system.

Wallet:  One per user, tracks current balance.
Transaction: Audit log of every credit/debit on a wallet.
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# ── Wallet Schemas ─────────────────────────────────────────────────────

class WalletBase(BaseModel):
    """Fields for wallet creation."""
    user_id: int
    currency: str = "USD"


class WalletCreate(WalletBase):
    """Schema for creating a wallet (auto-created on user approval)."""
    pass


class WalletResponse(BaseModel):
    """Public wallet schema returned in API responses."""
    id: int
    user_id: int
    balance: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Transaction Schemas ────────────────────────────────────────────────

class TransactionCreate(BaseModel):
    """
    Schema for creating a new transaction (credit or debit).

    Attributes:
        wallet_id:        The wallet to credit/debit.
        amount:           The amount (always positive).
        transaction_type: "credit" (add money) or "debit" (remove money).
        description:      Reason for the transaction.
        reference_id:     Optional link to a project or task.
    """
    wallet_id: int
    amount: Decimal
    transaction_type: str       # "credit" or "debit"
    description: Optional[str] = None
    reference_id: Optional[str] = None


class TransactionResponse(BaseModel):
    """Public transaction schema returned in API responses."""
    id: int
    wallet_id: int
    amount: Decimal
    transaction_type: str
    description: Optional[str] = None
    reference_id: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WalletWithTransactions(WalletResponse):
    """Wallet response that includes the full transaction history."""
    transactions: List[TransactionResponse] = []
