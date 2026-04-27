"""store_hashed_product_api_keys

Revision ID: 8f3a1b2c4d5e
Revises: 71cccecd61d7
Create Date: 2026-04-27 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.security import hash_product_api_key

# revision identifiers, used by Alembic.
revision: str = "8f3a1b2c4d5e"
down_revision: Union[str, Sequence[str], None] = "71cccecd61d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("products", sa.Column("api_key_id", sa.String(length=64), nullable=True))
    op.add_column("products", sa.Column("api_key_hash", sa.String(length=255), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, api_key FROM products")).fetchall()
    for row in rows:
        api_key = row.api_key
        api_key_parts = api_key.split("_", 2) if api_key else []
        api_key_id = api_key_parts[1] if len(api_key_parts) == 3 and api_key_parts[1] else f"legacy_{row.id}"
        bind.execute(
            sa.text(
                "UPDATE products SET api_key_id = :api_key_id, api_key_hash = :api_key_hash WHERE id = :id"
            ),
            {
                "id": row.id,
                "api_key_id": api_key_id,
                "api_key_hash": hash_product_api_key(api_key),
            },
        )

    op.alter_column("products", "api_key_id", nullable=False)
    op.alter_column("products", "api_key_hash", nullable=False)
    op.create_index(op.f("ix_products_api_key_id"), "products", ["api_key_id"], unique=True)
    op.create_index(op.f("ix_products_api_key_hash"), "products", ["api_key_hash"], unique=True)

    op.drop_index(op.f("ix_products_api_key"), table_name="products")
    op.drop_column("products", "api_key")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("products", sa.Column("api_key", sa.String(length=255), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, api_key_hash FROM products")).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE products SET api_key = :api_key WHERE id = :id"),
            {"id": row.id, "api_key": row.api_key_hash},
        )

    op.alter_column("products", "api_key", nullable=False)
    op.create_index(op.f("ix_products_api_key"), "products", ["api_key"], unique=True)

    op.drop_index(op.f("ix_products_api_key_hash"), table_name="products")
    op.drop_index(op.f("ix_products_api_key_id"), table_name="products")
    op.drop_column("products", "api_key_hash")
    op.drop_column("products", "api_key_id")
