"""add_fwd_growth_to_watchlist

Revision ID: f8a6b3c9d1e2
Revises: e7f5a9b8c1d2
Create Date: 2026-03-08 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a6b3c9d1e2'
down_revision: Union[str, None] = 'e7f5a9b8c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('watchlist_items', sa.Column('fwd_revenue_growth', sa.Float(), nullable=True))
    op.add_column('watchlist_items', sa.Column('fwd_eps_growth', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('watchlist_items', 'fwd_eps_growth')
    op.drop_column('watchlist_items', 'fwd_revenue_growth')
