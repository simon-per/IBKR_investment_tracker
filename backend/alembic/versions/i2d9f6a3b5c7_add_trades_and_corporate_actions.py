"""add_trades_and_corporate_actions_tables

Revision ID: i2d9f6a3b5c7
Revises: h1c8e5f2a4b6
Create Date: 2026-07-24 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i2d9f6a3b5c7'
down_revision: Union[str, None] = 'h1c8e5f2a4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ib_key', sa.String(64), nullable=False),
        sa.Column('conid', sa.String(32), nullable=False),
        sa.Column('security_id', sa.Integer(),
                  sa.ForeignKey('securities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('trade_date', sa.Date(), nullable=False),
        sa.Column('buy_sell', sa.String(16), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 6), nullable=False),
        sa.Column('price', sa.Numeric(18, 6), nullable=True),
        sa.Column('proceeds', sa.Numeric(18, 6), nullable=True),
        sa.Column('commission', sa.Numeric(18, 6), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('realized_pnl', sa.Numeric(18, 6), nullable=True),
        sa.Column('asset_category', sa.String(16), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('ib_key', name='uq_trades_ib_key'),
    )
    op.create_index('ix_trades_conid', 'trades', ['conid'])
    op.create_index('ix_trades_security_id', 'trades', ['security_id'])
    op.create_index('ix_trades_trade_date', 'trades', ['trade_date'])
    op.create_index('ix_trades_conid_date', 'trades', ['conid', 'trade_date'])

    op.create_table(
        'corporate_actions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ib_key', sa.String(64), nullable=False),
        sa.Column('conid', sa.String(32), nullable=False),
        sa.Column('security_id', sa.Integer(),
                  sa.ForeignKey('securities.id', ondelete='SET NULL'), nullable=True),
        sa.Column('symbol', sa.String(64), nullable=True),
        sa.Column('action_date', sa.Date(), nullable=False),
        sa.Column('action_type', sa.String(32), nullable=False),
        sa.Column('quantity', sa.Numeric(18, 6), nullable=True),
        sa.Column('value', sa.Numeric(18, 6), nullable=True),
        sa.Column('proceeds', sa.Numeric(18, 6), nullable=True),
        sa.Column('currency', sa.String(3), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('ib_key', name='uq_corp_actions_ib_key'),
    )
    op.create_index('ix_corp_actions_conid', 'corporate_actions', ['conid'])
    op.create_index('ix_corp_actions_security_id', 'corporate_actions', ['security_id'])
    op.create_index('ix_corp_actions_action_date', 'corporate_actions', ['action_date'])
    op.create_index('ix_corp_actions_conid_date', 'corporate_actions', ['conid', 'action_date'])


def downgrade() -> None:
    op.drop_index('ix_corp_actions_conid_date', table_name='corporate_actions')
    op.drop_index('ix_corp_actions_action_date', table_name='corporate_actions')
    op.drop_index('ix_corp_actions_security_id', table_name='corporate_actions')
    op.drop_index('ix_corp_actions_conid', table_name='corporate_actions')
    op.drop_table('corporate_actions')

    op.drop_index('ix_trades_conid_date', table_name='trades')
    op.drop_index('ix_trades_trade_date', table_name='trades')
    op.drop_index('ix_trades_security_id', table_name='trades')
    op.drop_index('ix_trades_conid', table_name='trades')
    op.drop_table('trades')
