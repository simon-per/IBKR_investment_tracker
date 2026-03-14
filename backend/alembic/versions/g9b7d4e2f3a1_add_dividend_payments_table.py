"""add_dividend_payments_table

Revision ID: g9b7d4e2f3a1
Revises: f8a6b3c9d1e2
Create Date: 2026-03-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g9b7d4e2f3a1'
down_revision: Union[str, None] = 'f8a6b3c9d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dividend_payments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('security_id', sa.Integer(), sa.ForeignKey('securities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ex_date', sa.Date(), nullable=False),
        sa.Column('amount_per_share', sa.Numeric(18, 6), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('shares_held', sa.Numeric(18, 6), nullable=True),
        sa.Column('gross_amount_eur', sa.Numeric(18, 6), nullable=True),
        sa.Column('last_computed', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('security_id', 'ex_date', name='uix_dividend_security_exdate'),
    )
    op.create_index('ix_dividend_payments_id', 'dividend_payments', ['id'])
    op.create_index('ix_dividend_payments_security_id', 'dividend_payments', ['security_id'])
    op.create_index('ix_dividend_payments_ex_date', 'dividend_payments', ['ex_date'])


def downgrade() -> None:
    op.drop_table('dividend_payments')
