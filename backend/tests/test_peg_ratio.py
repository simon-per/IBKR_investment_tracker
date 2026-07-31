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
