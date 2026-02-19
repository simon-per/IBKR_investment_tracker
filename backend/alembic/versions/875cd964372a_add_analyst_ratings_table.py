"""add_analyst_ratings_table

Revision ID: 875cd964372a
Revises: 0fe97bf472da
Create Date: 2026-02-02 17:18:43.894288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '875cd964372a'
down_revision: Union[str, None] = '0fe97bf472da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analyst_ratings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('security_id', sa.Integer(), nullable=False),
        sa.Column('strong_buy', sa.Integer(), nullable=False, default=0),
        sa.Column('buy', sa.Integer(), nullable=False, default=0),
        sa.Column('hold', sa.Integer(), nullable=False, default=0),
        sa.Column('sell', sa.Integer(), nullable=False, default=0),
        sa.Column('strong_sell', sa.Integer(), nullable=False, default=0),
        sa.Column('last_updated', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['security_id'], ['securities.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_analyst_ratings_security_id', 'analyst_ratings', ['security_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_analyst_ratings_security_id', table_name='analyst_ratings')
    op.drop_table('analyst_ratings')
