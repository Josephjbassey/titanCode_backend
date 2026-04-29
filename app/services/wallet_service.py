from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.models import Wallet, Transaction


class WalletServiceError(Exception):
    pass


class WalletNotFoundError(WalletServiceError):
    pass


class DuplicateTransactionError(WalletServiceError):
    pass


class InsufficientFundsError(WalletServiceError):
    pass


class WalletService:
    @staticmethod
    async def apply_transaction(
        db: AsyncSession,
        *,
        wallet_id: int,
        amount: Decimal,
        transaction_type: str,
        description: Optional[str] = None,
        reference_id: Optional[str] = None,
    ) -> tuple[Transaction, Wallet, bool]:
        if amount <= 0:
            raise WalletServiceError("Amount must be positive")
        if transaction_type not in {"credit", "debit"}:
            raise WalletServiceError("Transaction type must be 'credit' or 'debit'")

        try:
            async with db.begin():
                wallet_row = await db.execute(
                    select(Wallet).where(Wallet.id == wallet_id).with_for_update()
                )
                wallet = wallet_row.scalars().first()
                if not wallet:
                    raise WalletNotFoundError("Wallet not found")

                if reference_id:
                    existing_row = await db.execute(
                        select(Transaction).where(
                            Transaction.wallet_id == wallet_id,
                            Transaction.reference_id == reference_id,
                            Transaction.transaction_type == transaction_type,
                            Transaction.amount == amount,
                        )
                    )
                    existing = existing_row.scalars().first()
                    if existing:
                        return existing, wallet, True

                if transaction_type == "debit":
                    if wallet.balance < amount:
                        raise InsufficientFundsError(f"Insufficient funds. Current balance: {wallet.balance}")
                    wallet.balance = wallet.balance - amount
                else:
                    wallet.balance = wallet.balance + amount

                transaction = Transaction(
                    wallet_id=wallet_id,
                    amount=amount,
                    transaction_type=transaction_type,
                    description=description,
                    reference_id=reference_id,
                )
                db.add(transaction)

            await db.refresh(wallet)
            await db.refresh(transaction)
            return transaction, wallet, False
        except IntegrityError as exc:
            await db.rollback()
            raise DuplicateTransactionError("Duplicate transaction detected") from exc
