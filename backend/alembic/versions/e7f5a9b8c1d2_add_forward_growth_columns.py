"""add_forward_growth_columns

Revision ID: e7f5a9b8c1d2
Revises: d6e4f8a9b2c3
Create Date: 2026-03-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f5a9b8c1d2'
down_revision: Union[str, None] = 'd6e4f8a9b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('fundamental_metrics', sa.Column('fwd_revenue_growth', sa.Float(), nullable=True))
    op.add_column('fundamental_metrics', sa.Column('fwd_eps_growth', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('fundamental_metrics', 'fwd_eps_growth')
    op.drop_column('fundamental_metrics', 'fwd_revenue_growth')
