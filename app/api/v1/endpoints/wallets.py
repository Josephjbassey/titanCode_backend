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
from app.services.wallet_service import (
    WalletService,
    WalletServiceError,
    WalletNotFoundError,
    InsufficientFundsError,
)

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
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get a specific user's wallet with history.
    
    BOLA PROTECTION (Constraint #4):
    - CEO/Admin can see ANY wallet.
    - Regular users can ONLY see their OWN wallet.
    """
    # Authorization logic
    if current_user.role not in ["CEO", "Admin"] and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You can only access your own wallet details"
        )
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
    try:
        transaction, wallet, idempotent_replay = await WalletService.apply_transaction(
            db,
            wallet_id=txn_in.wallet_id,
            amount=txn_in.amount,
            transaction_type=txn_in.transaction_type,
            description=txn_in.description,
            reference_id=txn_in.reference_id,
        )
    except WalletNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientFundsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except WalletServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Step 6: Send a real-time notification to the wallet owner
    emoji = "💰" if txn_in.transaction_type == "credit" else "💸"
    action = "credited to" if txn_in.transaction_type == "credit" else "debited from"
    await notification_manager.send_personal_message(
        user_id=wallet.user_id,
        message={
            "type": "wallet",
            "title": f"Wallet {txn_in.transaction_type.capitalize()} {emoji}",
            "message": (
                f"${transaction.amount:.2f} has been {action} your wallet. "
                f"New balance: ${wallet.balance:.2f}. "
                f"Reason: {transaction.description or 'N/A'}"
                + (" (idempotent replay ignored)" if idempotent_replay else "")
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
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    Get the full transaction history for a specific wallet.
    
    BOLA PROTECTION (Constraint #4):
    - CEO/Admin can see ANY wallet history.
    - Regular users can ONLY see their OWN wallet history.
    """
    # 1. Fetch the wallet to verify ownership
    res = await db.execute(select(Wallet).where(Wallet.id == wallet_id))
    wallet = res.scalars().first()
    
    if not wallet:
        raise HTTPException(status_code=404, detail="Wallet not found")

    # 2. Authorization logic
    if current_user.role not in ["CEO", "Admin"] and current_user.id != wallet.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You can only access your own transaction history"
        )
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
