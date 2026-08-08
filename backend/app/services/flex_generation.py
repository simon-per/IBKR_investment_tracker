"""
IBKR's one statement generation per day, and how to tell whether it is spent.

**IBKR generates this account's Flex statement about once per US-Eastern calendar day.**
Every attempt after the day's first success is refused with `Code=1001` at the
*SendRequest* step — the fatal-fast kind, not the "keep polling" kind. Read off this
account's own `sync_runs` on 2026-08-08, grouped by ET day:

    ET day   00:00 ET   02:00 ET   12-13 ET   18:00 ET
    08-01    success    error                 error
    08-02    error      success    error      error
    08-03    error      success    error      error
    08-04    success    error                 error
    08-05    success    error                 error
    08-06    success    error      error      error
    08-07    success    error                 error
    08-08    success    error

Exactly one success per ET day, always the earliest attempt that works, everything
after it refused. Twelve days, zero counterexamples. The only two-success ET day in
the whole history is 07-31, the day the query definition was edited in the portal —
an edit appears to reset it, which is why the callers keep a `force` escape hatch.

**Asking anyway is not free, which is the reason this module exists rather than a
comment.** A `1001` at the request step means IBKR tried to generate and failed, and
failed generations are precisely what `Code=1025` counts — the undocumented token
lockout that has cost this account hours of syncing three times. So a doomed attempt
does not merely produce a red row in the history; it spends the budget that protects
every future sync.

Naive-UTC in, naive-UTC out, per `app/clock.py`: these values are compared against
`sync_runs.finished_at`, which is naive UTC.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clock import utcnow
from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)

# IBKR's statement day is measured in New York — not Berlin and not UTC. `whenGenerated`
# is stamped in ET, and the "Last N Calendar Days" window rolls at midnight there: a
# statement downloaded at 05:40 Berlin still read `to=20260805`, because that is 23:40
# the previous day in New York. Resolved from the system tz database (verified present
# in `python:3.11-slim`), so no extra dependency.
ET = ZoneInfo("America/New_York")

# Sync types that spend IBKR's one daily generation, i.e. that call the Flex Web Service.
#
# `ibkr_manual_xml` is deliberately absent, and that is empirical rather than assumed.
# The browser download and the Web Service serve the same statement over **independent**
# channels, so an offline ingest costs no generation — proven twice in this account's
# history, where an offline ingest was followed by a *successful* API generation in the
# same ET day (07-28: 00:16 ET then 02:05 ET; 07-31: 00:07 ET then 02:07 ET). Counting
# it here would suppress the day's real attempt on exactly the days someone had just
# recovered by hand.
FLEX_API_SYNC_TYPES = ('ibkr', 'ibkr_sync', 'full_sync')

# Sync types that mean "the data was refreshed", which is a different question from the
# one above and must not be collapsed into it: the offline path genuinely updates the
# portfolio, so it resets a staleness clock even though it spends no generation. Written
# as an extension of the set above rather than as a second literal, because two tuples
# listing overlapping sync types is precisely how this codebase's duplicated logic drifts.
IBKR_SYNC_TYPES = FLEX_API_SYNC_TYPES + ('ibkr_manual_xml',)


def et_date(moment: datetime) -> date:
    """The US-Eastern calendar date a naive-UTC instant falls on."""
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(ET).date()


def et_day_bounds_utc(moment: datetime) -> tuple[datetime, datetime]:
    """
    The `[start, end)` of `moment`'s ET calendar day, as naive UTC.

    Bounded at both ends rather than just below so an injected `as_of` cannot see rows
    from after it — the tests pin the boundary from both sides, which is what catches a
    UTC-vs-ET slip. Midnight is safe to construct in any US DST year: the transitions
    happen at 02:00 local, so 00:00 always exists and is never ambiguous.
    """
    day = et_date(moment)
    start = datetime.combine(day, time.min, tzinfo=ET)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ET)
    return (
        start.astimezone(timezone.utc).replace(tzinfo=None),
        end.astimezone(timezone.utc).replace(tzinfo=None),
    )


def next_generation_opens_at(as_of: Optional[datetime] = None) -> datetime:
    """
    When IBKR can next be asked for a statement — the next midnight ET, as naive UTC.

    Note this is also the moment the *window* rolls forward, so it is genuinely "when
    newer data exists", not merely when the refusal lifts.
    """
    _, end = et_day_bounds_utc(as_of or utcnow())
    return end


async def last_generation_today(
    db: AsyncSession, as_of: Optional[datetime] = None
) -> Optional[datetime]:
    """
    When today's Flex generation was spent, or None if it is still available.

    Keys on a **successful** run: a day full of failures has not consumed anything, and
    must not stop the next slot from trying. That is the case the 08-02 and 08-03
    recoveries depended on.
    """
    as_of = as_of or utcnow()
    start, end = et_day_bounds_utc(as_of)

    result = await db.execute(
        select(func.max(SyncRun.finished_at)).where(
            and_(
                SyncRun.sync_type.in_(FLEX_API_SYNC_TYPES),
                SyncRun.status == 'success',
                SyncRun.finished_at >= start,
                SyncRun.finished_at < end,
            )
        )
    )
    return result.scalar_one_or_none()


async def generation_already_spent(
    db: AsyncSession, as_of: Optional[datetime] = None
) -> Optional[datetime]:
    """
    `last_generation_today`, but **failing open** — the answer every caller should use.

    An unreadable sync history means we cannot tell whether today's generation is spent,
    and the two ways to be wrong are not symmetric. Failing *closed* would skip the sync,
    and a skipped sync is invisible: no error, no warning, just a portfolio that quietly
    stops updating — the exact silent-outage shape that hid the 730-day pass for four
    days. Failing *open* costs at most one refused request.

    Kept separate from `last_generation_today` rather than swallowing inside it, so the
    query stays honest for tests and so the policy is stated once for both callers
    instead of being decided twice.
    """
    try:
        return await last_generation_today(db, as_of)
    except Exception as e:
        logger.warning(
            "Could not tell whether today's Flex generation is spent (%s) — asking IBKR "
            "anyway rather than skipping a sync", e,
        )
        return None
