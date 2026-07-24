"""add_withholding_and_net_to_dividend_payments

Revision ID: k4f1b8c5d7e9
Revises: j3e0a7b4c6d8
Create Date: 2026-07-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k4f1b8c5d7e9'
down_revision: Union[str, None] = 'j3e0a7b4c6d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('dividend_payments', sa.Column('withholding_tax_eur', sa.Numeric(18, 6), nullable=True))
    op.add_column('dividend_payments', sa.Column('net_amount_eur', sa.Numeric(18, 6), nullable=True))
    op.add_column('dividend_payments', sa.Column('pay_date', sa.Date(), nullable=True))
    # 'ibkr' (authoritative cash transactions) or 'yfinance_estimate' (fallback).
    op.add_column('dividend_payments', sa.Column('source', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('dividend_payments', 'source')
    op.drop_column('dividend_payments', 'pay_date')
    op.drop_column('dividend_payments', 'net_amount_eur')
    op.drop_column('dividend_payments', 'withholding_tax_eur')
