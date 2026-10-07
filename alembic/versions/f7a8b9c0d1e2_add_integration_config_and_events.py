"""add integration_config and integration_events tables

Revision ID: f7a8b9c0d1e2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa


revision = 'f7a8b9c0d1e2'
down_revision = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'integration_configs',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('service_name', sa.String(64), nullable=False, unique=True, index=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('credentials_json', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'integration_events',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('integration_id', sa.Integer(), sa.ForeignKey('integration_configs.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('payload_json', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='success'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('integration_events')
    op.drop_table('integration_configs')
