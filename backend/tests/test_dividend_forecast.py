"""
Unit tests for the pure dividend forecast inference (app/services/dividend_forecast.py).

The forecast invents nothing: cadence comes from the spacing of past ex-dates,
the size from the recent dividend per share scaled to the holding we have now,
and every "can't know" case must refuse ([]), not guess.

Working per share is what lets a recently bought payer be forecast at all — the
schedule belongs to the company, not to how long we have owned it.
"""
from datetime import date
from decimal import Decimal

from app.services.dividend_forecast import (
    ForecastPayment,
    HistPayment,
    infer_gap_days,
    project_dividends,
)


def _hist(dates, per_share="1"):
    return [
        HistPayment(
            on_date=d,
            per_share_eur=Decimal(per_share) if per_share is not None else None,
        )
        for d in dates
    ]


QUARTERLY = [date(2025, 10, 15), date(2026, 1, 15), date(2026, 4, 15)]


def test_quarterly_cadence_is_inferred():
    assert infer_gap_days(QUARTERLY) == 91


def test_a_single_payment_has_no_cadence():
    assert infer_gap_days([date(2026, 1, 15)]) is None


def test_slower_than_annual_is_not_a_cadence():
    assert infer_gap_days([date(2024, 1, 1), date(2025, 6, 1), date(2026, 12, 1)]) is None


def test_subweekly_noise_is_not_a_cadence():
    dates = [date(2026, 1, d) for d in (1, 8, 15, 22)]
    assert infer_gap_days(dates) is None


def test_projection_lands_inside_the_horizon_only():
    out = project_dividends(
        _hist(QUARTERLY), Decimal("10"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 12, 31),
    )
    # last ex-date 2026-04-15 stepped by 91 days: 07-15 and 10-14; 2027-01-13 is out
    assert [fp.on_date for fp in out] == [date(2026, 7, 15), date(2026, 10, 14)]
    assert all(fp.net_eur == Decimal("10") for fp in out)   # 1/share x 10 shares


def test_a_stopped_payer_is_not_resurrected():
    out = project_dividends(
        _hist(QUARTERLY), Decimal("10"),
        horizon_start=date(2027, 2, 1), horizon_end=date(2027, 12, 31),
    )
    assert out == []


def test_the_amount_follows_the_current_holding():
    out = project_dividends(
        _hist(QUARTERLY, per_share="2"), Decimal("25"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 8, 1),
    )
    assert out == [ForecastPayment(on_date=date(2026, 7, 15), net_eur=Decimal("50"))]


def test_median_resists_a_special_dividend():
    history = _hist(QUARTERLY) + [
        HistPayment(on_date=date(2026, 4, 20), per_share_eur=Decimal("40"))
    ]
    out = project_dividends(
        history, Decimal("10"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 9, 1),
    )
    assert out and all(fp.net_eur == Decimal("10") for fp in out)


def test_nothing_held_projects_nothing():
    assert project_dividends(_hist(QUARTERLY), Decimal("0"),
                             date(2026, 5, 2), date(2026, 12, 31)) == []


def test_dates_without_amounts_still_establish_the_cadence():
    """
    A payment we can't price still proves the schedule; only one priced payment
    in the sample is needed to size the projection.
    """
    history = [
        HistPayment(on_date=QUARTERLY[0], per_share_eur=None),
        HistPayment(on_date=QUARTERLY[1], per_share_eur=None),
        HistPayment(on_date=QUARTERLY[2], per_share_eur=Decimal("3")),
    ]
    out = project_dividends(history, Decimal("10"),
                            date(2026, 5, 2), date(2026, 8, 1))
    assert out == [ForecastPayment(on_date=date(2026, 7, 15), net_eur=Decimal("30"))]


def test_a_schedule_with_no_priced_payment_refuses():
    history = _hist(QUARTERLY, per_share=None)
    assert project_dividends(history, Decimal("10"),
                             date(2026, 5, 2), date(2026, 12, 31)) == []


def test_a_full_future_year_is_projected():
    """
    The whole of next year, not just the remainder of this one — and asking
    about a distant horizon must not make a current payer look stopped.
    """
    out = project_dividends(
        _hist(QUARTERLY), Decimal("10"),
        horizon_start=date(2027, 1, 1), horizon_end=date(2027, 12, 31),
        as_of=date(2026, 5, 1),
    )
    assert [fp.on_date.year for fp in out] == [2027] * len(out)
    assert len(out) == 4   # quarterly


def test_staleness_is_judged_from_now_not_from_the_horizon():
    """A payer that really has stopped stays stopped, however far out we look."""
    out = project_dividends(
        _hist(QUARTERLY), Decimal("10"),
        horizon_start=date(2027, 1, 1), horizon_end=date(2027, 12, 31),
        as_of=date(2027, 1, 1),   # ~9 months since the last ex-date
    )
    assert out == []
