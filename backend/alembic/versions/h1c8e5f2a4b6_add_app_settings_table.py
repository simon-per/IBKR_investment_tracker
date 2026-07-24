"""add_app_settings_table

Revision ID: h1c8e5f2a4b6
Revises: g9b7d4e2f3a1
Create Date: 2026-07-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1c8e5f2a4b6'
down_revision: Union[str, None] = 'g9b7d4e2f3a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(64), primary_key=True),
        sa.Column('value', sa.String(255), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # Seed the default base currency so the app has a value immediately.
    op.execute("INSERT INTO app_settings (key, value) VALUES ('base_currency', 'EUR')")


def downgrade() -> None:
    op.drop_table('app_settings')
