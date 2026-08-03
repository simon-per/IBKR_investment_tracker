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

   Pre-existing rows are left NULL, because nothing records when they were really
   set and NULL is how this schema says "unknown". An earlier revision backfilled
   CURRENT_TIMESTAMP instead, reasoning that "a NULL would make every security look
   suspect on the first run of the detector" — which has the comparison backwards.
   The detector warns when `newest_estimate < updated_at` and skips outright when
   `updated_at IS NULL` (`find_dividends_predating_their_mapping`, and the same
   guard in `manage_mappings list`), so NULL is the quiet value and now() is the
   loud one: stamping every row with the migration's own run time made every
   mapping read as *just changed*, and every estimate computed before it as
   fetched under some other ticker.

   That is not hypothetical — it fired on prod. All 20 rows carried the identical
   stamp 2026-07-30 19:49:16, including two pinned by hand three days earlier, and
   Samsung, SK Hynix and TSMC warned on every market-data sync with the estimates
   the forecast needs. The rows were correct; only this backfill said otherwise.
   Worse, it could not self-clear: `get_uncomputed()` keys on `shares_held IS NULL`
   and a pre-ownership row settles at 0, so `last_computed` never moves again.
   Purging — which the warning itself advises — would have deleted the only
   per-share history three recently-bought payers had to project from.

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
    # Deliberately not backfilled: a pre-existing row's real timestamps are
    # unknown, and NULL is the only value that says so. Stamping now() would date
    # every mapping to this migration and make the provenance detector read every
    # estimate older than it as fetched under a different ticker. Rows written from
    # here on get honest values from the model's server_default/onupdate.
    with op.batch_alter_table('ticker_mappings') as batch:
        batch.add_column(sa.Column('created_at', sa.DateTime(), nullable=True))
        batch.add_column(sa.Column('updated_at', sa.DateTime(), nullable=True))


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
