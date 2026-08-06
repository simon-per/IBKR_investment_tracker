"""
PEG from a P/E and a growth estimate — the arithmetic, and that the two services
that report it agree.

The defect: the formula was duplicated in `FundamentalsService` and
`WatchlistService`, and the *resolution orders* had diverged. Both tried Yahoo's
own `pegRatio` first, but the watchlist then tried forward-EPS growth (its own
comment calls that tier "preferred") before the analyst 5-year CAGR, while
fundamentals went straight to the CAGR with **no forward-EPS tier at all**. So one
security could show a PEG on `/api/watchlist` and a different one — or none — on
`/api/fundamentals/portfolio`. Exactly what `ttm_growth` was extracted to end,
between the same two services.

Offline: pure arithmetic plus one structural check, no network.
"""

import inspect

import pytest

from app.services.peg_ratio import growth_pct_from_estimate, peg_from_growth


class TestGrowthNormalisation:
    def test_a_decimal_estimate_is_scaled_to_a_percent(self):
        # yfinance sends 0.30 meaning 30%.
        assert growth_pct_from_estimate(0.30) == pytest.approx(30.0)

    def test_an_estimate_already_in_percent_is_left_alone(self):
        assert growth_pct_from_estimate(30.0) == pytest.approx(30.0)

    def test_the_boundary_is_one(self):
        assert growth_pct_from_estimate(0.999) == pytest.approx(99.9)
        assert growth_pct_from_estimate(1.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("bad", [None, 0, -0.15, -20])
    def test_a_missing_or_non_positive_estimate_has_no_percent(self, bad):
        """
        The guard that matters: `< 1` is true for *every* negative, so without the
        `<= 0` refusal a −20% estimate already in percent would be scaled to
        −2000%. Both call sites relied on their own `> 0` check for this; it now
        lives with the arithmetic instead of beside it.
        """
        assert growth_pct_from_estimate(bad) is None


class TestPeg:
    def test_divides_the_pe_by_the_growth_percent(self):
        # A P/E of 30 against 30% growth is the textbook PEG of 1.
        assert peg_from_growth(30.0, 0.30) == pytest.approx(1.0)

    def test_reads_a_percent_estimate_the_same_way(self):
        assert peg_from_growth(30.0, 30.0) == pytest.approx(1.0)

    @pytest.mark.parametrize("pe", [None, 0, -12.0])
    def test_refuses_without_a_usable_pe(self, pe):
        # A loss-making company has no meaningful PEG, and a negative one would
        # rank as attractively low wherever PEG is scored.
        assert peg_from_growth(pe, 0.30) is None

    @pytest.mark.parametrize("growth", [None, 0, -0.10])
    def test_refuses_without_a_usable_growth_estimate(self, growth):
        assert peg_from_growth(25.0, growth) is None

    def test_a_tiny_growth_estimate_yields_a_large_peg_rather_than_an_error(self):
        # 25 / 1% = 25. Expensive, but a real answer rather than a division fault.
        assert peg_from_growth(25.0, 0.01) == pytest.approx(25.0)


def _peg_block(func) -> str:
    return inspect.getsource(func)


def test_both_services_resolve_peg_in_the_same_order():
    """
    Structural rather than behavioural, because exercising either service means
    faking a yfinance `.info` frame — but the defect was *order*, and order is
    visible in the source.

    Pins that each service tries forward-EPS growth before the long-term CAGR, and
    that both route through the shared helper rather than reimplementing it.
    """
    from app.services.fundamentals_service import FundamentalsService
    from app.services.watchlist_service import WatchlistService

    for func in (FundamentalsService._extract_metrics, WatchlistService.sync_item):
        src = _peg_block(func)
        assert "peg_from_growth" in src, f"{func.__qualname__} does not use the shared helper"
        assert src.count("peg_from_growth") >= 2, (
            f"{func.__qualname__} has fewer than two PEG fallback tiers — the "
            f"forward-EPS tier is what fundamentals used to be missing"
        )
        fwd = src.index("fwd_eps")
        lt = src.index("longTermGrowth")
        assert fwd < lt, (
            f"{func.__qualname__} consults longTermGrowth before forward EPS; the "
            f"watchlist calls the forward-EPS tier the preferred one, so both must "
            f"try it first or the two endpoints disagree"
        )


def test_neither_service_still_normalises_growth_inline():
    """The duplicated `* 100 if < 1` heuristic must not come back beside the shared one."""
    from app.services import fundamentals_service, watchlist_service

    for module in (fundamentals_service, watchlist_service):
        src = inspect.getsource(module)
        assert "* 100 if" not in src, (
            f"{module.__name__} normalises a growth estimate inline again — that is "
            f"the duplication peg_ratio.py exists to remove"
        )


# ---------------------------------------------------------------------------
# The decimal-vs-percent inference is wrong in the direction that matters.
#
# `growth_estimates['+1y']['stockTrend']` is a decimal fraction that legitimately exceeds
# 1 whenever a company is expected to grow more than 100%. The inference read anything
# >= 1 as already-a-percent, so 222% growth became 2.2245% and a PEG of 0.25 became
# 24.56 — a factor of 100, in the direction that makes a fast grower look catastrophically
# overvalued. Three of this account's watchlist rows carry such a value today.
#
# That the column is a decimal is not a judgement call: the same value is stored as
# `fwd_eps_growth` and rendered by the UI as `(v * 100).toFixed(1)%`.
# ---------------------------------------------------------------------------


def test_a_fraction_above_one_is_not_mistaken_for_a_percent():
    # SNDK, live: P/E 54.64, +1y stockTrend 2.2245 (i.e. 222% growth).
    assert peg_from_growth(54.64, 2.2245, is_fraction=True) == pytest.approx(54.64 / 222.45)
    # The inference, left to itself, is 100x out.
    assert peg_from_growth(54.64, 2.2245) == pytest.approx(54.64 / 2.2245)


def test_the_scoring_consequence_of_getting_that_wrong():
    """A 10-point swing on the buy score's 25-point valuation block."""
    ladder = lambda p: 10 if p <= 0.5 else 8 if p <= 1 else 6 if p <= 1.5 else 4 if p <= 2 else 2 if p <= 3 else 0
    right = peg_from_growth(54.64, 2.2245, is_fraction=True)
    wrong = peg_from_growth(54.64, 2.2245)
    assert ladder(right) == 10
    assert ladder(wrong) == 0


def test_a_known_fraction_below_one_is_unchanged_by_the_flag():
    """The common case must be identical either way, or the flag would be a second rule."""
    for growth in (0.05, 0.15, 0.30, 0.999):
        assert peg_from_growth(20.0, growth, is_fraction=True) == peg_from_growth(20.0, growth)


def test_the_long_term_tier_keeps_inferring():
    """
    `longTermGrowth` has no established convention in this codebase, so its tier keeps the
    inference rather than assuming. The flag is opt-in precisely so one tier can know its
    input while the other admits it does not.
    """
    assert growth_pct_from_estimate(15) == 15          # read as a percent
    assert growth_pct_from_estimate(0.15) == pytest.approx(15)   # read as a fraction


def test_a_non_positive_growth_is_still_refused_under_the_flag():
    for bad in (None, 0, -0.2):
        assert growth_pct_from_estimate(bad, is_fraction=True) is None
        assert peg_from_growth(20.0, bad, is_fraction=True) is None
