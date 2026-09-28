"""add auth_provider and nullable password

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'e5f6a7b8c9d0'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make password_hash nullable for OAuth-only users
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=True)
    # 2. Add auth_provider column with default 'local'
    op.add_column('users', sa.Column('auth_provider', sa.String(length=50), server_default='local', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'auth_provider')
    op.alter_column('users', 'password_hash', existing_type=sa.String(length=255), nullable=False)
