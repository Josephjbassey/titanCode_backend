from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Wallet, Transaction


@dataclass
class WalletReconciliationRow:
    wallet_id: int
    recorded_balance: Decimal
    ledger_balance: Decimal
    delta: Decimal


async def ensure_transaction_recorded(db: AsyncSession, *, wallet_id: int, reference_id: str) -> None:
    tx_exists = (
        await db.execute(
            select(Transaction.id).where(
                Transaction.wallet_id == wallet_id,
                Transaction.reference_id == reference_id,
            )
        )
    ).scalar_one_or_none()
    if tx_exists is None:
        raise RuntimeError(f"Financial integrity violation: missing transaction for wallet={wallet_id}, ref={reference_id}")


async def reconcile_wallet_ledgers(db: AsyncSession) -> list[WalletReconciliationRow]:
    rows = (
        await db.execute(
            select(
                Wallet.id,
                Wallet.balance,
                func.coalesce(
                    func.sum(
                        Transaction.amount
                        * case((Transaction.transaction_type == "credit", 1), else_=-1)
                    ),
                    Decimal("0.00"),
                ).label("ledger_balance"),
            )
            .outerjoin(Transaction, Transaction.wallet_id == Wallet.id)
            .group_by(Wallet.id)
        )
    ).all()

    return [
        WalletReconciliationRow(
            wallet_id=row[0],
            recorded_balance=Decimal(row[1]),
            ledger_balance=Decimal(row[2]),
            delta=Decimal(row[1]) - Decimal(row[2]),
        )
        for row in rows
    ]
