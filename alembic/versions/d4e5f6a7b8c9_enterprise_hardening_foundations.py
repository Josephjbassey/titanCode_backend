"""enterprise hardening foundations

Revision ID: d4e5f6a7b8c9
Revises: 8f3a1b2c4d5e
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = 'd4e5f6a7b8c9'
down_revision = '8f3a1b2c4d5e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint('ck_users_role', 'users', "role IN ('CEO', 'Admin', 'Manager', 'Assistant', 'Member', 'Applicant', 'Client')")
    op.create_check_constraint('ck_users_status', 'users', "status IN ('pending', 'approved', 'rejected')")
    op.create_check_constraint('ck_applications_status', 'applications', "status IN ('pending', 'approved', 'rejected')")
    op.create_check_constraint('ck_projects_status', 'projects', "status IN ('pending', 'active', 'completed', 'cancelled')")

    op.create_table(
        'webhook_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('payload_hash', sa.String(length=128), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'event_id', name='uq_webhook_provider_event')
    )

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('actor_type', sa.String(length=50), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=100), nullable=False),
        sa.Column('target_type', sa.String(length=50), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_table('webhook_events')
    op.drop_constraint('ck_projects_status', 'projects', type_='check')
    op.drop_constraint('ck_applications_status', 'applications', type_='check')
    op.drop_constraint('ck_users_status', 'users', type_='check')
    op.drop_constraint('ck_users_role', 'users', type_='check')
