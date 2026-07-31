"""
Coercing a yfinance value into a number, and the two services agreeing about it.

`_safe_float` and `_safe_int` were a private copy on each of `FundamentalsService`
and `WatchlistService`. `_safe_int` was byte-identical; `_safe_float` had already
drifted — the watchlist rounded to four decimals, fundamentals did not — so the
same security's trailing P/E read `28.453125` on one endpoint and `28.4531` on the
other. Once `peg_ratio` was extracted, the *same computed PEG* was displayed to
different precision on the two screens.

The NaN case is the one that matters for correctness rather than presentation: a
NaN in a numeric column compares false against itself and serialises to invalid
JSON, so it has to become None before it is stored.

Offline: pure conversion, no network.
"""

import pytest

from app.services.fundamentals_service import FundamentalsService
from app.services.safe_numbers import DISPLAY_DIGITS, safe_float, safe_int
from app.services.watchlist_service import WatchlistService


class TestSafeFloat:
    def test_converts_a_number(self):
        assert safe_float(28.45) == 28.45

    def test_converts_a_numeric_string(self):
        # yfinance hands back strings for some fields.
        assert safe_float("1.5") == 1.5

    def test_rounds_to_the_display_precision(self):
        assert safe_float(28.453125) == 28.4531
        assert DISPLAY_DIGITS == 4

    def test_keeps_full_precision_when_asked(self):
        assert safe_float(28.453125, digits=None) == 28.453125

    @pytest.mark.parametrize("bad", [None, "", "n/a", object()])
    def test_anything_unconvertible_is_none(self, bad):
        assert safe_float(bad) is None

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_nan_and_infinity_are_none(self, bad):
        # Not presentation: a NaN in a numeric column compares false against
        # itself and serialises to invalid JSON.
        assert safe_float(bad) is None

    def test_zero_survives(self):
        # `if not value` would drop it; zero is a real figure here.
        assert safe_float(0) == 0.0

    def test_a_negative_survives(self):
        assert safe_float(-12.3456789) == -12.3457


class TestSafeInt:
    def test_truncates_rather_than_rounding(self):
        # Counts and market caps: the fractional part is float round-trip noise.
        assert safe_int(3.9) == 3

    def test_accepts_a_float_string(self):
        assert safe_int("42.0") == 42

    @pytest.mark.parametrize("bad", [None, "", "n/a", float("nan"), float("inf")])
    def test_anything_unusable_is_none(self, bad):
        assert safe_int(bad) is None

    def test_zero_survives(self):
        assert safe_int(0) == 0


@pytest.mark.parametrize(
    "value",
    [28.453125, 0.2537891, -3.14159265, 0, 1e9, float("nan"), None, "1.23456789"],
)
def test_both_services_coerce_identically(value):
    """
    The divergence itself. These are the two endpoints that display the same
    metrics for the same security, so a value must not read differently
    depending on which one you look at.
    """
    fundamentals = FundamentalsService.__new__(FundamentalsService)
    watchlist = WatchlistService.__new__(WatchlistService)

    assert fundamentals._safe_float(value) == watchlist._safe_float(value) or (
        fundamentals._safe_float(value) is None and watchlist._safe_float(value) is None
    )
    assert fundamentals._safe_int(value) == watchlist._safe_int(value) or (
        fundamentals._safe_int(value) is None and watchlist._safe_int(value) is None
    )


def test_both_services_route_through_the_shared_helper():
    """Structural: a re-inlined copy would pass the equality test above on the day
    it was written and drift afterwards, which is exactly what happened before."""
    import inspect

    for service in (FundamentalsService, WatchlistService):
        src = inspect.getsource(service._safe_float)
        assert "safe_float(" in src, f"{service.__name__} does not delegate"
        assert "math.isnan" not in src, (
            f"{service.__name__} has re-inlined the conversion — that is the "
            f"duplication safe_numbers.py exists to remove"
        )
