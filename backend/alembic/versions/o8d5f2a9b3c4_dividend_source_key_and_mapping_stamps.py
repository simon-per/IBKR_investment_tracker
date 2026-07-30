"""dividend_source_key_and_mapping_stamps

Two changes that together let a wrong ticker mapping be detected instead of
silently poisoning derived data. Both come out of the SBI case, where two
dividend rows written under a bare-symbol US listing survived the mapping's
correction to SBI.TO and went on defining a gold miner's payout schedule.

1. dividend_payments: widen the identity from (security_id, ex_date) to
   (security_id, source, ex_date).

   The column means two different things depending on the source — a real ex-date
   for yfinance rows, the *pay* date for IBKR rows — and the old constraint forced
   them to share one slot. When a payer's ex-to-pay lag lands on another record's
   date the two overwrote each other: real withholding relabelled an estimate, or
   amount_per_share nulled out, dropping the security below the two-sample
   threshold the forecast needs. Mastercard's 29-day lag already exceeds a monthly
   payer's whole cycle, so this is reachable, not theoretical.

   Verified before writing this: every row carries a non-NULL source (so there is
   no NULL-distinctness trap), and no security holds two sources on one date — so
   widening the key is a pure relaxation that cannot collide with existing data.

2. ticker_mappings: add created_at / updated_at.

   The table that decides where every price and every dividend comes from carried
   no timestamps at all, which makes "did this cached data come from the mapping
   in force today?" unanswerable — the question whose absence let SBI go unnoticed
   for months. With updated_at, a dividend row older than its mapping's last
   change is a specific, checkable suspicion rather than a guess from staleness.

   Backfilled to now() rather than left NULL: the rows exist, and a NULL would
   make every security look suspect on the first run of the detector that reads
   this. Existing mappings therefore read as "as old as this migration", which is
   the truthful floor — nothing records when they were really set.

SQLite cannot drop a constraint in place, so (1) goes through batch_alter_table,
which rebuilds the table. The container runs `alembic upgrade head` on every
start and auto-deploy backs the DB up first.

Revision ID: o8d5f2a9b3c4
Revises: n7c4e1f8a2b3
Create Date: 2026-07-30 19:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'o8d5f2a9b3c4'
down_revision: Union[str, None] = 'n7c4e1f8a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Source-aware dividend identity -------------------------------
    # A row with no source cannot participate in a source-scoped key in a
    # meaningful way (SQLite treats NULLs as distinct, so it would silently
    # permit duplicates). There are none today; stamp any that appear.
    op.execute(
        "UPDATE dividend_payments SET source = 'yfinance_estimate' WHERE source IS NULL"
    )
    with op.batch_alter_table('dividend_payments') as batch:
        batch.drop_constraint('uix_dividend_security_exdate', type_='unique')
        batch.create_unique_constraint(
            'uix_dividend_security_source_exdate',
            ['security_id', 'source', 'ex_date'],
        )

    # --- 2. Mapping provenance -------------------------------------------
    with op.batch_alter_table('ticker_mappings') as batch:
        batch.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE ticker_mappings "
        "SET created_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE created_at IS NULL"
    )


def downgrade() -> None:
    # Checked BEFORE any DDL, deliberately. Re-narrowing the key cannot succeed
    # over data the wider key allowed: any security holding both an estimate and
    # an IBKR row on the same date now has two rows where the old constraint
    # permits one. Refusing up front leaves the schema untouched — raising midway
    # would drop the mapping columns and then abort, half-downgraded.
    conn = op.get_bind()
    collisions = conn.execute(sa.text(
        "SELECT security_id, ex_date, COUNT(*) c FROM dividend_payments "
        "GROUP BY security_id, ex_date HAVING c > 1"
    )).fetchall()
    if collisions:
        listed = ", ".join(f"security_id={r[0]} on {r[1]}" for r in collisions[:10])
        raise RuntimeError(
            f"Cannot restore the (security_id, ex_date) key: {len(collisions)} "
            f"date(s) hold rows from both sources ({listed}). Clear the estimates "
            f"first — `python -m app.cli.purge_dividend_estimates <SYMBOL> "
            f"<EXCHANGE>` — then re-run this downgrade."
        )

    with op.batch_alter_table('ticker_mappings') as batch:
        batch.drop_column('updated_at')
        batch.drop_column('created_at')

    with op.batch_alter_table('dividend_payments') as batch:
        batch.drop_constraint('uix_dividend_security_source_exdate', type_='unique')
        batch.create_unique_constraint(
            'uix_dividend_security_exdate', ['security_id', 'ex_date']
        )
