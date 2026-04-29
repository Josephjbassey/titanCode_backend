"""add client_invoices table

Revision ID: 9a7b6c5d4e3f
Revises: c1d2e3f4a5b6
Create Date: 2026-04-29 20:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9a7b6c5d4e3f'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'client_invoices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('invoice_id', sa.String(length=64), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('client_email', sa.String(length=255), nullable=False),
        sa.Column('total_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('payment_url', sa.String(length=1000), nullable=True),
        sa.Column('provider_reference', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('draft', 'sent', 'payment_pending', 'paid', 'failed', 'cancelled')", name='ck_client_invoices_status'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_client_invoices_id'), 'client_invoices', ['id'], unique=False)
    op.create_index(op.f('ix_client_invoices_invoice_id'), 'client_invoices', ['invoice_id'], unique=True)
    op.create_index(op.f('ix_client_invoices_project_id'), 'client_invoices', ['project_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_client_invoices_project_id'), table_name='client_invoices')
    op.drop_index(op.f('ix_client_invoices_invoice_id'), table_name='client_invoices')
    op.drop_index(op.f('ix_client_invoices_id'), table_name='client_invoices')
    op.drop_table('client_invoices')
