"""
Unit tests for the pure dividend forecast inference (app/services/dividend_forecast.py).

The forecast invents nothing: cadence comes from the spacing of past payments,
the amount from trailing payments scaled to the current holding, and every
"can't know" case must refuse ([]), not guess.
"""
from datetime import date
from decimal import Decimal

from app.services.dividend_forecast import (
    ForecastPayment,
    HistPayment,
    infer_gap_days,
    project_dividends,
)


def _hist(dates, net="10", shares="10"):
    return [
        HistPayment(
            on_date=d,
            net_eur=Decimal(net),
            shares_held=Decimal(shares) if shares is not None else None,
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
    # last payment 2026-04-15 stepped by 91 days: 07-15 and 10-14; 2027-01-13 is past the horizon
    assert [fp.on_date for fp in out] == [date(2026, 7, 15), date(2026, 10, 14)]
    assert all(fp.net_eur == Decimal("10") for fp in out)


def test_a_stopped_payer_is_not_resurrected():
    # Last paid 2026-04-15, quarterly; by 2027-02 it has skipped ~3 payouts.
    out = project_dividends(
        _hist(QUARTERLY), Decimal("10"),
        horizon_start=date(2027, 2, 1), horizon_end=date(2027, 12, 31),
    )
    assert out == []


def test_amount_scales_to_the_current_holding():
    out = project_dividends(
        _hist(QUARTERLY, net="10", shares="10"), Decimal("20"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 8, 1),
    )
    assert out == [ForecastPayment(on_date=date(2026, 7, 15), net_eur=Decimal("20"))]


def test_median_resists_a_special_dividend():
    history = _hist(QUARTERLY) + [
        HistPayment(on_date=date(2026, 4, 20), net_eur=Decimal("100"), shares_held=Decimal("10"))
    ]
    out = project_dividends(
        history, Decimal("10"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 9, 1),
    )
    assert out and all(fp.net_eur == Decimal("10") for fp in out)


def test_nothing_held_projects_nothing():
    assert project_dividends(_hist(QUARTERLY), Decimal("0"),
                             date(2026, 5, 2), date(2026, 12, 31)) == []


def test_unknown_share_counts_fall_back_to_the_unscaled_amount():
    # IBKR rows may not resolve a held-share count; the raw net is used as-is.
    out = project_dividends(
        _hist(QUARTERLY, shares=None), Decimal("37"),
        horizon_start=date(2026, 5, 2), horizon_end=date(2026, 8, 1),
    )
    assert out == [ForecastPayment(on_date=date(2026, 7, 15), net_eur=Decimal("10"))]
