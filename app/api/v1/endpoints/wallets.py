"""
TitanCode Technologies — Wallet Endpoints
===========================================
This module handles wallet management and financial transactions.
Every approved user gets a wallet. Admins can credit/debit wallets
for project payments, bonuses, and withdrawals.

Who can do what (RBAC):
    • Any authenticated user → Can view their own wallet and transactions.
    • CEO, Admin             → Can view any wallet, credit/debit wallets.

API Routes (all prefixed with /api/v1/wallets):
    POST /create            — Create a wallet for a user (Admin+)
    GET  /me                — Get the current user's wallet + transactions
    GET  /{user_id}         — Get any user's wallet (Admin+)
    POST /transaction       — Credit or debit a wallet (Admin+)
    GET  /{wallet_id}/history — Get transaction history for a wallet (Admin+)
"""

from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from typing import Any, List

from app.core.notifications import manager as notification_manager

from app.db.database import get_db
from app.db.models import Wallet, Transaction, User
from app.schemas.wallet import (
    WalletCreate,
    WalletResponse,
    WalletWithTransactions,
    TransactionCreate,
    TransactionResponse,
)
from app.api.v1.endpoints.auth import get_current_user, RoleChecker

# Create a new router instance — registered in main.py
router = APIRouter()

# ── RBAC Dependencies ──────────────────────────────────────────────────
allow_admin = RoleChecker(["CEO", "Admin"])


# ═══════════════════════════════════════════════════════════════════════
# POST /wallets/create — Create a wallet for a user
# ═══════════════════════════════════════════════════════════════════════
@router.post("/create", response_model=WalletResponse, status_code=status.HTTP_201_CREATED)
async def create_wallet(
    wallet_in: WalletCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Create a new wallet for a user.

    Each user can only have ONE wallet (enforced by unique constraint).
    Typically called automatically when a user is approved, but can
    also be created manually by an admin.

    Args:
        wallet_in: Wallet data (user_id, currency).

    Returns:
        WalletResponse: The newly created wallet.

    Raises:
        HTTPException 400: If the user already has a wallet.
    """
    # Step 1: Check if the user already has a wallet
    result = await db.execute(
        select(Wallet).where(Wallet.user_id == wallet_in.user_id)
    )
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="User already has a wallet")

    # Step 2: Create the wallet with initial balance of 0
    wallet = Wallet(**wallet_in.model_dump())
    db.add(wallet)
    await db.commit()
    await db.refresh(wallet)
    return wallet


# ═══════════════════════════════════════════════════════════════════════
# GET /wallets/me — Get the current user's wallet
# ═══════════════════════════════════════════════════════════════════════
@router.get("/me", response_model=WalletWithTransactions)
async def get_my_wallet(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get the authenticated user's wallet with their full transaction history.

    Any authenticated user can view their own wallet — this is how team
    members check their earnings and payment history.

    Returns:
        WalletWithTransactions: Wallet details + list of all transactions.

    Raises:
        HTTPException 404: If the user doesn't have a wallet yet.
    """
    # Eager-load transactions in the same query to avoid N+1 problem
    result = await db.execute(
        select(Wallet)
        .options(selectinload(Wallet.transactions))
        .where(Wallet.user_id == current_user.id)
    )
    wallet = result.scalars().first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found. Contact an admin.")
    return wallet


# ═══════════════════════════════════════════════════════════════════════
# GET /wallets/{user_id} — Get any user's wallet (Admin only)
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{user_id}", response_model=WalletWithTransactions)
async def get_user_wallet(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Get any user's wallet with their full transaction history.
    Restricted to CEO and Admin for financial oversight.

    Args:
        user_id: The ID of the user whose wallet to retrieve.

    Returns:
        WalletWithTransactions: Wallet details + list of all transactions.

    Raises:
        HTTPException 404: If the user doesn't have a wallet.
    """
    result = await db.execute(
        select(Wallet)
        .options(selectinload(Wallet.transactions))
        .where(Wallet.user_id == user_id)
    )
    wallet = result.scalars().first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found for this user")
    return wallet


# ═══════════════════════════════════════════════════════════════════════
# POST /wallets/transaction — Credit or debit a wallet
# ═══════════════════════════════════════════════════════════════════════
@router.post("/transaction", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    txn_in: TransactionCreate,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Credit or debit a user's wallet.

    This is the core financial operation:
        • "credit" → adds money (e.g., project payment, bonus)
        • "debit"  → removes money (e.g., withdrawal, fee)

    The wallet balance is updated atomically alongside the transaction
    record to ensure consistency.

    Args:
        txn_in: Transaction data (wallet_id, amount, type, description).

    Returns:
        TransactionResponse: The recorded transaction.

    Raises:
        HTTPException 404: If the wallet doesn't exist.
        HTTPException 400: If the transaction type is invalid or
                           insufficient funds for a debit.
    """
    # Step 1: Find the wallet
    result = await db.execute(select(Wallet).where(Wallet.id == txn_in.wallet_id))
    wallet = result.scalars().first()
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # Step 2: Validate transaction type
    if txn_in.transaction_type not in ("credit", "debit"):
        raise HTTPException(
            status_code=400,
            detail="Transaction type must be 'credit' or 'debit'",
        )

    # Step 3: Apply the balance change
    if txn_in.transaction_type == "credit":
        wallet.balance = wallet.balance + txn_in.amount
    else:
        # Prevent overdrawing — can't debit more than the balance
        if wallet.balance < txn_in.amount:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient funds. Current balance: {wallet.balance}",
            )
        wallet.balance = wallet.balance - txn_in.amount

    # Step 4: Create the transaction record (audit trail)
    transaction = Transaction(**txn_in.model_dump())
    db.add(transaction)

    # Step 5: Save both the wallet update and new transaction atomically
    await db.commit()
    await db.refresh(transaction)

    # Step 6: Send a real-time notification to the wallet owner
    emoji = "💰" if txn_in.transaction_type == "credit" else "💸"
    action = "credited to" if txn_in.transaction_type == "credit" else "debited from"
    await notification_manager.send_personal_message(
        user_id=wallet.user_id,
        message={
            "type": "wallet",
            "title": f"Wallet {txn_in.transaction_type.capitalize()} {emoji}",
            "message": (
                f"${txn_in.amount:.2f} has been {action} your wallet. "
                f"New balance: ${wallet.balance:.2f}. "
                f"Reason: {txn_in.description or 'N/A'}"
            ),
        },
    )

    return transaction


# ═══════════════════════════════════════════════════════════════════════
# GET /wallets/{wallet_id}/history — Transaction history
# ═══════════════════════════════════════════════════════════════════════
@router.get("/{wallet_id}/history", response_model=List[TransactionResponse])
async def get_transaction_history(
    wallet_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(allow_admin),
) -> Any:
    """
    Get the full transaction history for a specific wallet.
    Results are ordered newest-first.

    Args:
        wallet_id: The ID of the wallet to get history for.

    Returns:
        List[TransactionResponse]: All transactions for this wallet.
    """
    result = await db.execute(
        select(Transaction)
        .where(Transaction.wallet_id == wallet_id)
        .order_by(Transaction.created_at.desc())
    )
    return result.scalars().all()
