"""Add buy score and valuation columns to watchlist_items

Revision ID: d6e4f8a9b2c3
Revises: c5d3e7f8a1b2
Create Date: 2026-03-06 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6e4f8a9b2c3'
down_revision: Union[str, None] = 'c5d3e7f8a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('watchlist_items', sa.Column('forward_pe', sa.Float(), nullable=True))
    op.add_column('watchlist_items', sa.Column('peg_ratio', sa.Float(), nullable=True))
    op.add_column('watchlist_items', sa.Column('ev_to_ebitda', sa.Float(), nullable=True))
    op.add_column('watchlist_items', sa.Column('analyst_target', sa.Float(), nullable=True))
    op.add_column('watchlist_items', sa.Column('analyst_rating', sa.String(20), nullable=True))
    op.add_column('watchlist_items', sa.Column('analyst_count', sa.Integer(), nullable=True))
    op.add_column('watchlist_items', sa.Column('buy_score', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('watchlist_items', 'buy_score')
    op.drop_column('watchlist_items', 'analyst_count')
    op.drop_column('watchlist_items', 'analyst_rating')
    op.drop_column('watchlist_items', 'analyst_target')
    op.drop_column('watchlist_items', 'ev_to_ebitda')
    op.drop_column('watchlist_items', 'peg_ratio')
    op.drop_column('watchlist_items', 'forward_pe')
