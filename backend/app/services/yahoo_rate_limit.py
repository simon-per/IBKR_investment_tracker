"""
One definition of "Yahoo is rate-limiting us", shared by every service that loops.

Rule 1 in CLAUDE.md is that a rate limit means **stop immediately**, because
continuing is what turns a short block into a long one. `MarketDataService` learned
that on 2026-08-04: its detection aborted the ticker *variations* for the security in
hand while the caller logged the failure and moved on to the next of forty, asking the
same IP again seconds later.

Three other services still had the older shape — `FundamentalsService`,
`AnalystRatingService` and `WatchlistService` all caught, logged and continued — and
fundamentals is the most expensive of the four at roughly five Yahoo calls per
security. So the predicate lives here rather than being copied a fourth time, which is
what this codebase's dominant failure mode would predict happening to it.

**The marker list is deliberately narrower than CLAUDE.md's symptom list.** That
document also names "HTTP 404 with `Expecting value: line 1 column 1 (char 0)`" and
empty JSON as things a rate limit can look like, and those are **not** matched here on
purpose: they are equally what a delisted or mistyped ticker looks like, and
`_try_fetch_yahoo` uses this same verdict to decide whether to go on trying ticker
*variations*. Treating a JSON-decode failure as a rate limit would abort auto-discovery
for every security Yahoo simply does not know, which is a real cost paid on good data.
The markers below are unambiguous: nothing but a rate limit says "429".

The asymmetry that decides the default: a false positive costs one pass of freshness
and the next slot recovers it, because the dates never reached are simply still
missing. A false negative spends the rest of the pass hammering a limited IP.
"""

RATE_LIMIT_MARKERS = ("429", "too many requests", "rate limit", "blocked")


def is_rate_limit(error: object) -> bool:
    """
    True when an exception (or message) is Yahoo refusing us for volume.

    Takes ``object`` rather than ``BaseException`` because two callers hold only the
    stringified error: ``WatchlistService.sync_all`` reads the ``{"error": str(e)}``
    that ``sync_item`` returns, and the market-data path lowercases the message before
    testing. Both must reach the same verdict as a caller holding the exception.
    """
    if error is None:
        return False
    text = str(error).lower()
    return any(marker in text for marker in RATE_LIMIT_MARKERS)
