"""add_fundamentals_tables

Revision ID: b4c8d2e6f7a9
Revises: a3b7c1d2e4f5
Create Date: 2026-03-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c8d2e6f7a9'
down_revision: Union[str, None] = 'a3b7c1d2e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fundamental metrics table (one-to-one with securities)
    op.create_table(
        'fundamental_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('security_id', sa.Integer(), nullable=False),
        sa.Column('trailing_pe', sa.Float(), nullable=True),
        sa.Column('forward_pe', sa.Float(), nullable=True),
        sa.Column('peg_ratio', sa.Float(), nullable=True),
        sa.Column('price_to_sales', sa.Float(), nullable=True),
        sa.Column('price_to_book', sa.Float(), nullable=True),
        sa.Column('revenue_growth', sa.Float(), nullable=True),
        sa.Column('earnings_growth', sa.Float(), nullable=True),
        sa.Column('profit_margins', sa.Float(), nullable=True),
        sa.Column('gross_margins', sa.Float(), nullable=True),
        sa.Column('operating_margins', sa.Float(), nullable=True),
        sa.Column('market_cap', sa.BigInteger(), nullable=True),
        sa.Column('number_of_analysts', sa.Integer(), nullable=True),
        sa.Column('target_mean_price', sa.Float(), nullable=True),
        sa.Column('target_high_price', sa.Float(), nullable=True),
        sa.Column('target_low_price', sa.Float(), nullable=True),
        sa.Column('quote_type', sa.String(20), nullable=True),
        sa.Column('data_currency', sa.String(10), nullable=True),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['security_id'], ['securities.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_fundamental_metrics_security_id', 'fundamental_metrics', ['security_id'], unique=True)

    # Earnings events table (one-to-many with securities)
    op.create_table(
        'earnings_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('security_id', sa.Integer(), nullable=False),
        sa.Column('earnings_date', sa.DateTime(), nullable=False),
        sa.Column('eps_estimate', sa.Float(), nullable=True),
        sa.Column('reported_eps', sa.Float(), nullable=True),
        sa.Column('surprise_percent', sa.Float(), nullable=True),
        sa.Column('is_upcoming', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['security_id'], ['securities.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('security_id', 'earnings_date', name='uix_security_earnings_date'),
    )
    op.create_index('ix_earnings_events_security_id', 'earnings_events', ['security_id'])
    op.create_index('ix_earnings_events_date', 'earnings_events', ['earnings_date'])


def downgrade() -> None:
    op.drop_index('ix_earnings_events_date', table_name='earnings_events')
    op.drop_index('ix_earnings_events_security_id', table_name='earnings_events')
    op.drop_table('earnings_events')
    op.drop_index('ix_fundamental_metrics_security_id', table_name='fundamental_metrics')
    op.drop_table('fundamental_metrics')
