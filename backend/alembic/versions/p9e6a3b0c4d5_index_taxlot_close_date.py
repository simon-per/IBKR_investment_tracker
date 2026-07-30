"""index_taxlot_close_date

`realized_rows_from_closed_lots()` filters
`is_open = false AND close_date IS NOT NULL AND close_date BETWEEN ? AND ?`, and it
backs `/portfolio/value-over-time`, `/annualized-return`, `/attribution`,
`/summary` and the tax report — the shared helper that keeps the portfolio totals
and the tax report from disagreeing, so every one of those pays for it.

`taxlots` indexes (open_date, security_id), is_open, and (security_id, is_open).
None serves a range on close_date: the planner was left with `ix_is_open`, whose
cardinality is two, so it scanned the closed half of the table and filtered.

Leading with close_date makes it a range scan; is_open trails so the
`is_open = false` equality is served from the same index rather than a row fetch.
Small today (~1,000 lots) and it grows with every sale — the same reasoning as
migration n7c4e1f8a2b3.

Revision ID: p9e6a3b0c4d5
Revises: o8d5f2a9b3c4
Create Date: 2026-07-30 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'p9e6a3b0c4d5'
down_revision: Union[str, None] = 'o8d5f2a9b3c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_taxlots_close_date', 'taxlots', ['close_date', 'is_open'])


def downgrade() -> None:
    op.drop_index('ix_taxlots_close_date', table_name='taxlots')
