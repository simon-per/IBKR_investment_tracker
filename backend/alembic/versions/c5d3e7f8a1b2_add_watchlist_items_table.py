"""Add watchlist_items table

Revision ID: c5d3e7f8a1b2
Revises: b4c8d2e6f7a9
Create Date: 2026-03-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5d3e7f8a1b2'
down_revision: Union[str, None] = 'b4c8d2e6f7a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'watchlist_items',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('yahoo_ticker', sa.String(20), nullable=False, unique=True),
        sa.Column('symbol', sa.String(20), nullable=True),
        sa.Column('company_name', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('target_price', sa.Float(), nullable=True),
        sa.Column('current_price', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('trailing_pe', sa.Float(), nullable=True),
        sa.Column('revenue_growth', sa.Float(), nullable=True),
        sa.Column('earnings_growth', sa.Float(), nullable=True),
        sa.Column('profit_margins', sa.Float(), nullable=True),
        sa.Column('market_cap', sa.BigInteger(), nullable=True),
        sa.Column('week52_high', sa.Float(), nullable=True),
        sa.Column('week52_low', sa.Float(), nullable=True),
        sa.Column('pct_from_52w_high', sa.Float(), nullable=True),
        sa.Column('ma200', sa.Float(), nullable=True),
        sa.Column('ma50', sa.Float(), nullable=True),
        sa.Column('pct_from_ma200', sa.Float(), nullable=True),
        sa.Column('rsi14', sa.Float(), nullable=True),
        sa.Column('data_currency', sa.String(10), nullable=True),
        sa.Column('last_synced', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_watchlist_items_yahoo_ticker', 'watchlist_items', ['yahoo_ticker'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_watchlist_items_yahoo_ticker', table_name='watchlist_items')
    op.drop_table('watchlist_items')
