"""add_withdrawal_external_idempotency_key

Revision ID: c1e9a4f2b6d1
Revises: 8f3a1b2c4d5e
Create Date: 2026-04-27 00:00:01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1e9a4f2b6d1"
down_revision: Union[str, Sequence[str], None] = "8f3a1b2c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "withdrawals",
        sa.Column("external_payout_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.create_index(
        op.f("ix_withdrawals_external_payout_idempotency_key"),
        "withdrawals",
        ["external_payout_idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_withdrawals_external_payout_idempotency_key"), table_name="withdrawals")
    op.drop_column("withdrawals", "external_payout_idempotency_key")
