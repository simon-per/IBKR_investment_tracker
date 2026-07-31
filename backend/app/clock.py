"""
The one way to ask what time it is.

Every timestamp this application stores is a **naive UTC** datetime: the columns
default to `func.now()`, which SQLite answers in UTC, and `utc_iso()` in
`repositories/sync_run_repository.py` serializes them by stamping UTC onto a
value it assumes is already UTC.

The stdlib's argument-less `now()` does not produce that. It returns naive
*local* time, and the only reason the codebase got away with it at ~49 call
sites is that `python:3.11-slim` sets no `TZ`, so the container's local time
happens to be UTC. Nothing declared that dependency and nothing would have
noticed it breaking.

Off the container it is already wrong, in both directions at once:

- a cache cutoff (`now - timedelta(days=7)`) compared against a naive-UTC
  column expires entries an offset early;
- an age (`now - row.last_synced`) reads an offset too old;
- serializing it through `utc_iso()` labels local time as UTC, so the browser
  converts a second time — the "two clocks on one line" failure `utc_iso`'s own
  docstring was written about, reintroduced by its argument.

In summer Europe/Berlin that is two hours, which is why a local run showed a
sync timestamped in the future. Using this everywhere makes the naive-UTC
invariant true by construction instead of by accident of the base image.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """
    Now, as a **naive** UTC datetime.

    Naive on purpose: it is written into and compared against columns that hold
    naive datetimes, and mixing an aware value into that comparison raises
    `TypeError` rather than degrading. The goal is a correct UTC value in the
    existing convention, not a migration to aware timestamps.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
