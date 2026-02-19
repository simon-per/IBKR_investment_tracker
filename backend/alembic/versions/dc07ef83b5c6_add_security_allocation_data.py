"""add_security_allocation_data

Revision ID: dc07ef83b5c6
Revises: 875cd964372a
Create Date: 2026-02-02 18:19:59.049578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc07ef83b5c6'
down_revision: Union[str, None] = '875cd964372a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add allocation columns to securities table
    op.add_column('securities', sa.Column('sector', sa.String(), nullable=True))
    op.add_column('securities', sa.Column('industry', sa.String(), nullable=True))
    op.add_column('securities', sa.Column('country', sa.String(), nullable=True))
    op.add_column('securities', sa.Column('asset_type', sa.String(), nullable=True, server_default='Stock'))
    op.add_column('securities', sa.Column('allocation_last_updated', sa.DateTime(), nullable=True))


def downgrade() -> None:
    # Remove allocation columns
    op.drop_column('securities', 'allocation_last_updated')
    op.drop_column('securities', 'asset_type')
    op.drop_column('securities', 'country')
    op.drop_column('securities', 'industry')
    op.drop_column('securities', 'sector')
