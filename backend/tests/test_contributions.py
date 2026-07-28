"""
Tests for PortfolioService.get_contributions — average capital deployed per
month, from the cost basis of the lots opened in each month.

EUR base so no FX data is needed, and ``as_of`` is pinned in every test so the
trailing windows don't move with the calendar.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.app_settings import AppSetting
from app.services.portfolio_service import PortfolioService, _shift_months


async def _make_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [Security.__table__, TaxLot.__table__, AppSetting.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session = AsyncSession(engine, expire_on_commit=False)
    session.add(Security(
        id=1, isin="US0000000001", symbol="AAA", description="Test Co",
        currency="EUR", conid=100, asset_category="STK", exchange="XETRA",
    ))
    await session.flush()
    return engine, session


def _lot(open_date: date, cost: str, close_date: Optional[date] = None) -> TaxLot:
    return TaxLot(
        security_id=1,
        open_date=open_date,
        quantity=Decimal("10"),
        cost_basis=Decimal(cost),
        price_per_unit=Decimal(cost) / 10,
        currency="EUR",
        cost_basis_eur=Decimal(cost),
        is_open=close_date is None,
        close_date=close_date,
        close_source="trade" if close_date else None,
    )


def _window(report: dict, label: str) -> dict:
    return next(w for w in report["windows"] if w["label"] == label)


def _month(report: dict, month: str) -> dict:
    return next(m for m in report["monthly"] if m["month"] == month)


@pytest.mark.asyncio
async def test_buys_bucket_into_their_open_month():
    engine, session = await _make_session()
    try:
        session.add_all([
            _lot(date(2026, 1, 15), "1000"),
            _lot(date(2026, 1, 28), "500"),
            _lot(date(2026, 3, 4), "700"),
        ])
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 3, 31))

        assert [m["month"] for m in report["monthly"]] == ["2026-01", "2026-03"]
        assert _month(report, "2026-01")["net_eur"] == 1500.0
        assert _month(report, "2026-03")["net_eur"] == 700.0
        assert report["first_contribution_date"] == "2026-01-15"
        assert report["base_currency"] == "EUR"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_sale_releases_capital_in_its_close_month():
    engine, session = await _make_session()
    try:
        session.add(_lot(date(2026, 1, 10), "1000", close_date=date(2026, 3, 20)))
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 3, 31))

        # Deployed in January, released in March: net zero overall.
        assert _month(report, "2026-01") == {"month": "2026-01", "gross_eur": 1000.0, "net_eur": 1000.0}
        assert _month(report, "2026-03") == {"month": "2026-03", "gross_eur": 0.0, "net_eur": -1000.0}
        assert _window(report, "all")["net_eur"] == 0.0

        # The average is deployment, so the sale does not erase the January buy:
        # 1,000 was put to work regardless of it later coming back out.
        # 2026-01-10..2026-03-31 is 80 days = 2.63 months, so 1,000 / 2.63.
        w_all = _window(report, "all")
        assert w_all["gross_eur"] == 1000.0
        assert w_all["months"] == pytest.approx(2.63, abs=0.01)
        assert w_all["avg_per_month_eur"] == pytest.approx(380.5, abs=0.5)
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_partially_sold_lot_conserves_the_original_cost_in_the_open_month():
    """
    A partial sale splits the lot pro-rata (sync_helper Phase D), leaving an open
    remainder and a closed piece that share the original open_date. Both legs must
    land in the open month and sum back to the original cost.
    """
    engine, session = await _make_session()
    try:
        session.add_all([
            _lot(date(2026, 2, 5), "600"),                              # remainder, still open
            _lot(date(2026, 2, 5), "400", close_date=date(2026, 5, 9)),  # sold piece
        ])
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 5, 31))

        assert _month(report, "2026-02")["gross_eur"] == 1000.0
        assert _month(report, "2026-05")["net_eur"] == -400.0
        assert _window(report, "all")["net_eur"] == 600.0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_window_divisor_is_clamped_to_available_history():
    engine, session = await _make_session()
    try:
        # Four months of history, one 1,200 purchase at the start.
        session.add(_lot(date(2026, 1, 31), "1200"))
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 5, 31))

        w12 = _window(report, "12m")
        assert w12["partial"] is True
        assert w12["months"] == pytest.approx(3.94, abs=0.02)   # ~120 days, not 12 months
        assert w12["avg_per_month_eur"] == pytest.approx(304.5, abs=1.0)

        # A window shorter than the history is not partial, and excludes the buy.
        w3 = _window(report, "3m")
        assert w3["partial"] is False
        assert w3["months"] == 3.0
        assert w3["net_eur"] == 0.0

        assert _window(report, "all")["partial"] is False
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_averages_per_window_and_the_cost_basis_identity():
    engine, session = await _make_session()
    try:
        # 1,000/month for 12 months, plus one 500 sale released in the final month.
        for i in range(12):
            session.add(_lot(_shift_months(date(2026, 6, 15), 11 - i), "1000"))
        session.add(_lot(date(2025, 8, 15), "500", close_date=date(2026, 6, 2)))
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 6, 30))

        # 12 x 1,000 deployed + the 500 lot = 12,500 deployed; 500 came back out.
        w_all = _window(report, "all")
        assert w_all["gross_eur"] == 12500.0
        assert w_all["net_eur"] == 12000.0

        # 3M covers the Apr/May/Jun buys. The June sale reduces net but must NOT
        # reduce the average — the money was still deployed when it was deployed.
        w3 = _window(report, "3m")
        assert w3["months"] == 3.0
        assert w3["gross_eur"] == 3000.0
        assert w3["net_eur"] == 2500.0
        assert w3["avg_per_month_eur"] == pytest.approx(1000.0, abs=0.01)

        w6 = _window(report, "6m")
        assert w6["gross_eur"] == 6000.0
        assert w6["avg_per_month_eur"] == pytest.approx(1000.0, abs=0.01)

        # The 12M window reaches back past the first lot, so its divisor is clamped
        # to the 11.5 months that actually exist — 12,500 / 11.5, not / 12.
        w12 = _window(report, "12m")
        assert w12["partial"] is True
        assert w12["months"] == pytest.approx(11.50, abs=0.02)
        assert w12["gross_eur"] == 12500.0
        assert w12["avg_per_month_eur"] == pytest.approx(1087.0, abs=1.0)

        # Identity: every lot is either still open or was released, so the monthly
        # net must sum to the cost basis of the open lots — 12,000.
        assert round(sum(m["net_eur"] for m in report["monthly"]), 2) == 12000.0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_portfolio_reports_nothing_rather_than_dividing_by_zero():
    engine, session = await _make_session()
    try:
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 6, 30))

        assert report == {
            "windows": [],
            "monthly": [],
            "first_contribution_date": None,
            "base_currency": "EUR",
        }
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_portfolio_opened_today_does_not_divide_by_zero():
    engine, session = await _make_session()
    try:
        session.add(_lot(date(2026, 6, 30), "800"))
        await session.commit()

        report = await PortfolioService(session).get_contributions(as_of=date(2026, 6, 30))

        w_all = _window(report, "all")
        assert w_all["months"] > 0
        assert w_all["net_eur"] == 800.0
        assert w_all["avg_per_month_eur"] > 0
    finally:
        await session.close()
        await engine.dispose()


def test_shift_months_clamps_to_the_shorter_target_month():
    assert _shift_months(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert _shift_months(date(2024, 5, 31), 3) == date(2024, 2, 29)   # leap year
    assert _shift_months(date(2026, 3, 15), 12) == date(2025, 3, 15)
    assert _shift_months(date(2026, 1, 10), 3) == date(2025, 10, 10)  # year boundary
