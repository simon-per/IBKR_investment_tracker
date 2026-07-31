"""
PEG from a P/E and an analyst growth estimate.

Shared by ``FundamentalsService`` and ``WatchlistService`` for the same reason
``ttm_growth`` is: it lived inline in **both**, and the two had already diverged.

The formula was identical; the *resolution order* was not. Both tried Yahoo's own
``pegRatio`` first, but the watchlist then tried forward-EPS growth — its own
comment calls that tier "preferred" — before the analyst 5-year CAGR, while
fundamentals went straight to the CAGR and had **no forward-EPS tier at all**. So
a security Yahoo gives no ``pegRatio`` for could show one PEG on
``/api/watchlist`` and a different one, or none, on
``/api/fundamentals/portfolio`` — the same divergence, between the same two
services, that ``ttm_growth`` was extracted to end.

Closing it cost nothing: ``FundamentalsService`` already fetches
``growth_estimates`` and already computes ``fwd_eps`` from it for its own
``fwd_eps_growth`` column — it simply never fed it to the PEG fallback. Both
services now run the same three tiers in the same order over the same inputs.
"""
from typing import Optional


def growth_pct_from_estimate(growth: Optional[float]) -> Optional[float]:
    """
    Normalise an analyst growth estimate to a **percentage**.

    yfinance is inconsistent about whether these arrive as a decimal (``0.30``) or
    already as a percent (``30``), so the convention is inferred: below 1 it is
    read as a decimal and scaled.

    The ambiguity is real but narrow — it misreads only a value that is *already*
    a percent and below 1, i.e. sub-1% growth, which would become sub-100%. Both
    call sites guard on ``growth > 0`` before reaching here, so a negative
    estimate never takes the ``< 1`` branch and cannot be scaled by 100; that
    guard is load-bearing and is asserted in the tests rather than left implicit.

    Returns None for a missing, zero or negative estimate — a PEG divided by one
    of those is not a small number, it is meaningless.
    """
    if growth is None or growth <= 0:
        return None
    return growth * 100 if growth < 1 else growth


def peg_from_growth(trailing_pe: Optional[float], growth: Optional[float]) -> Optional[float]:
    """
    ``trailing_pe / growth%``, or None when either side is unusable.

    Refuses rather than guessing on a missing P/E, a non-positive P/E (a loss-making
    company has no meaningful PEG) or an unusable growth estimate.
    """
    if trailing_pe is None or trailing_pe <= 0:
        return None
    growth_pct = growth_pct_from_estimate(growth)
    if growth_pct is None:
        return None
    return trailing_pe / growth_pct
