"""add_cash_flows_table

Records external deposits and withdrawals, so "how much money did I add" stops
being inferred from tax lots. Lot cost basis cannot distinguish a purchase funded
by new money from one funded by selling something else: summing it counts rotated
capital twice, and netting closures out instead debits a window for a purchase made
before that window began. A deposit has one leg, so neither error applies.

Requires 'Deposits & Withdrawals' enabled under Cash Transactions in the Flex Query.
Until it is, the table stays empty and the contributions endpoint reports the
tax-lot deployment figure alone.

Revision ID: m6b3d0e7f9a1
Revises: l5a2c9d6e8f0
Create Date: 2026-07-28 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm6b3d0e7f9a1'
down_revision: Union[str, None] = 'l5a2c9d6e8f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cash_flows',
        sa.Column('id', sa.Integer(), nullable=False),
        # IBKR transactionID; the upsert key, so re-ingesting a statement is safe.
        sa.Column('ib_key', sa.String(64), nullable=False),
        sa.Column('flow_date', sa.Date(), nullable=False),
        sa.Column('flow_type', sa.String(16), nullable=False),  # 'DEPOSITWITHDRAW'
        # Signed as IBKR reports it: deposit positive, withdrawal negative.
        sa.Column('amount', sa.Numeric(18, 6), nullable=False),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('amount_eur', sa.Numeric(18, 6), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cash_flows_id', 'cash_flows', ['id'])
    op.create_index('ix_cash_flows_ib_key', 'cash_flows', ['ib_key'], unique=True)
    op.create_index('ix_cash_flows_flow_date', 'cash_flows', ['flow_date'])
    op.create_index('ix_cash_flows_flow_type', 'cash_flows', ['flow_type'])


def downgrade() -> None:
    op.drop_index('ix_cash_flows_flow_type', table_name='cash_flows')
    op.drop_index('ix_cash_flows_flow_date', table_name='cash_flows')
    op.drop_index('ix_cash_flows_ib_key', table_name='cash_flows')
    op.drop_index('ix_cash_flows_id', table_name='cash_flows')
    op.drop_table('cash_flows')
