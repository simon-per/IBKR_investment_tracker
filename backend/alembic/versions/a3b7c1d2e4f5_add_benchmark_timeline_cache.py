"""add_benchmark_timeline_cache

Revision ID: a3b7c1d2e4f5
Revises: 9f45ff029b69
Create Date: 2026-03-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b7c1d2e4f5'
down_revision: Union[str, None] = '9f45ff029b69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('benchmark_timeline_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('benchmark_key', sa.String(length=50), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('benchmark_value_eur', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('cost_basis_eur', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('gain_loss_eur', sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column('gain_loss_percent', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('benchmark_key', 'date', name='uix_benchmark_cache_key_date')
    )
    op.create_index(op.f('ix_benchmark_timeline_cache_id'), 'benchmark_timeline_cache', ['id'], unique=False)
    op.create_index(op.f('ix_benchmark_timeline_cache_benchmark_key'), 'benchmark_timeline_cache', ['benchmark_key'], unique=False)
    op.create_index(op.f('ix_benchmark_timeline_cache_date'), 'benchmark_timeline_cache', ['date'], unique=False)
    op.create_index('ix_benchmark_cache_key_date', 'benchmark_timeline_cache', ['benchmark_key', 'date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_benchmark_cache_key_date', table_name='benchmark_timeline_cache')
    op.drop_index(op.f('ix_benchmark_timeline_cache_date'), table_name='benchmark_timeline_cache')
    op.drop_index(op.f('ix_benchmark_timeline_cache_benchmark_key'), table_name='benchmark_timeline_cache')
    op.drop_index(op.f('ix_benchmark_timeline_cache_id'), table_name='benchmark_timeline_cache')
    op.drop_table('benchmark_timeline_cache')
