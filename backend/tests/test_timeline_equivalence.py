"""
The swept timeline must be NUMERICALLY IDENTICAL to the per-day per-lot loop it
replaced — same Decimal arithmetic, same skip rules, same rounding — across the
awkward shapes: closed lots, a same-day rotation, price gaps that exercise the
forward-fill, a non-EUR security, and a non-EUR base currency.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.portfolio_service import BaseFx, PortfolioService

START = date(2026, 3, 2)
END = date(2026, 4, 10)


def _sec(sid, sym, currency):
    return SimpleNamespace(id=sid, symbol=sym, currency=currency)


def _lot(open_date, qty, cost_eur, close_date=None):
    return SimpleNamespace(
        open_date=open_date, close_date=close_date,
        quantity=Decimal(qty), cost_basis_eur=Decimal(cost_eur),
    )


def _fixture():
    eur = _sec(1, "EUR1", "EUR")
    usd = _sec(2, "USD1", "USD")
    rot_old = _sec(3, "ROLD", "EUR")
    rot_new = _sec(4, "RNEW", "EUR")

    lots = [
        (_lot(date(2026, 1, 5), "10", "100"), eur),                       # held throughout
        (_lot(date(2026, 3, 10), "5", "50"), eur),                        # opens mid-range
        (_lot(date(2026, 2, 1), "8", "200", close_date=date(2026, 3, 25)), usd),  # closes mid-range
        (_lot(date(2026, 1, 10), "10", "110", close_date=date(2026, 3, 18)), rot_old),
        (_lot(date(2026, 3, 18), "10", "115"), rot_new),                  # same-day rotation
    ]

    # Prices with gaps (forward-fill must kick in); none for ROLD after the 17th
    # and none for RNEW before the 18th.
    price_cache = {1: {}, 2: {}, 3: {}, 4: {}}
    d = date(2026, 1, 5)
    while d <= END:
        if d.weekday() < 5 and d.day % 7 != 0:  # punch holes
            price_cache[1][d] = Decimal("11")
            price_cache[2][d] = Decimal("30")
            if d < date(2026, 3, 18):
                price_cache[3][d] = Decimal("11.5")
            if d >= date(2026, 3, 18):
                price_cache[4][d] = Decimal("11.6")
        d += timedelta(days=1)

    # USD->EUR with weekend gaps too.
    fx_cache = {"USD": {}}
    d = date(2026, 1, 5)
    while d <= END:
        if d.weekday() < 5:
            fx_cache["USD"][d] = Decimal("0.9")
        d += timedelta(days=1)

    currency_map = {1: "EUR", 2: "USD", 3: "EUR", 4: "EUR"}

    # Non-EUR base with a drifting rate, so per-date projection matters.
    base_rates = {}
    d = date(2026, 1, 1)
    while d <= END:
        base_rates[d] = Decimal("0.93") + Decimal(d.toordinal() % 5) / 1000
        d += timedelta(days=1)
    base_fx = BaseFx("CHF", base_rates)

    return lots, price_cache, fx_cache, currency_map, base_fx


@pytest.mark.parametrize("use_chf_base", [False, True])
def test_swept_timeline_equals_the_per_day_loop(use_chf_base):
    lots, price_cache, fx_cache, currency_map, chf_fx = _fixture()
    base_fx = chf_fx if use_chf_base else BaseFx("EUR", {})

    svc = PortfolioService.__new__(PortfolioService)  # sync methods need no DB

    swept = svc._calculate_timeline_swept(
        START, END, lots, price_cache, fx_cache, currency_map, base_fx,
    )

    per_day = []
    d = START
    while d <= END:
        if d.weekday() < 5:
            per_day.append(svc._calculate_daily_value(
                d, lots, price_cache, fx_cache,
                price_currency_cache=currency_map, base_fx=base_fx,
            ))
        d += timedelta(days=1)

    assert swept == per_day
    # Sanity that the fixture exercised what it claims to.
    assert any(row["cost_basis_eur"] != per_day[0]["cost_basis_eur"] for row in per_day)
