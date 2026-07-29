"""add_hot_path_indices

Two composite indices for query shapes the existing single-column indices
serve poorly:

- taxlots(security_id, is_open): reconciliation resolves each security's open
  lots on every sync; the planner previously had to pick either the security
  index or the is_open index and filter the rest.
- exchange_rates(from_currency, to_currency, date): the carry-forward lookup is
  an equality on the pair plus a range + ORDER BY on date. The unique
  constraint (date, from, to) leads with the ranged column, so it cannot serve
  that shape — this one can.

Revision ID: n7c4e1f8a2b3
Revises: m6b3d0e7f9a1
Create Date: 2026-07-29 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'n7c4e1f8a2b3'
down_revision: Union[str, None] = 'm6b3d0e7f9a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_taxlots_security_open', 'taxlots', ['security_id', 'is_open'])
    op.create_index(
        'ix_exchange_rates_pair_date', 'exchange_rates',
        ['from_currency', 'to_currency', 'date'],
    )


def downgrade() -> None:
    op.drop_index('ix_exchange_rates_pair_date', table_name='exchange_rates')
    op.drop_index('ix_taxlots_security_open', table_name='taxlots')
