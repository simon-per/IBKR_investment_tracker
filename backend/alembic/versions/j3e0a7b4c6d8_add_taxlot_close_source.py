"""add_close_source_to_taxlots

Revision ID: j3e0a7b4c6d8
Revises: i2d9f6a3b5c7
Create Date: 2026-07-24 09:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j3e0a7b4c6d8'
down_revision: Union[str, None] = 'i2d9f6a3b5c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('taxlots', sa.Column('close_source', sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column('taxlots', 'close_source')
