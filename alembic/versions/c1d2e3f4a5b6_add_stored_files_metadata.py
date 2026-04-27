"""add_stored_files_metadata

Revision ID: c1d2e3f4a5b6
Revises: 8f3a1b2c4d5e
Create Date: 2026-04-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, Sequence[str], None] = "8f3a1b2c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "stored_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("folder", sa.String(length=50), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("folder", "filename", name="uq_stored_files_folder_filename"),
        sa.UniqueConstraint("path"),
    )
    op.create_index(op.f("ix_stored_files_id"), "stored_files", ["id"], unique=False)
    op.create_index(op.f("ix_stored_files_folder"), "stored_files", ["folder"], unique=False)
    op.create_index(op.f("ix_stored_files_owner_id"), "stored_files", ["owner_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_stored_files_owner_id"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_folder"), table_name="stored_files")
    op.drop_index(op.f("ix_stored_files_id"), table_name="stored_files")
    op.drop_table("stored_files")
