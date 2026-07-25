"""add_sync_runs_table

Persists each sync attempt. SchedulerService.last_sync_result is in-memory only, so
it was lost on every container restart — and auto-deploy restarts on every push,
which left the daily validator unable to tell whether a sync had run.

Revision ID: l5a2c9d6e8f0
Revises: k4f1b8c5d7e9
Create Date: 2026-07-25 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l5a2c9d6e8f0'
down_revision: Union[str, None] = 'k4f1b8c5d7e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'sync_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        # 'ibkr' | 'full_sync' | 'ibkr_sync' | 'market_data_only'
        sa.Column('sync_type', sa.String(32), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),  # success | error
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_runs_id', 'sync_runs', ['id'])
    op.create_index('ix_sync_runs_sync_type', 'sync_runs', ['sync_type'])
    op.create_index('ix_sync_runs_status', 'sync_runs', ['status'])
    op.create_index('ix_sync_runs_finished_at', 'sync_runs', ['finished_at'])
    op.create_index('ix_sync_runs_type_finished', 'sync_runs', ['sync_type', 'finished_at'])


def downgrade() -> None:
    op.drop_index('ix_sync_runs_type_finished', table_name='sync_runs')
    op.drop_index('ix_sync_runs_finished_at', table_name='sync_runs')
    op.drop_index('ix_sync_runs_status', table_name='sync_runs')
    op.drop_index('ix_sync_runs_sync_type', table_name='sync_runs')
    op.drop_index('ix_sync_runs_id', table_name='sync_runs')
    op.drop_table('sync_runs')
