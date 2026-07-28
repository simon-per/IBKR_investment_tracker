"""
Service tests for the dividends breakdown endpoint and the era-spliced summary.

The splice is the money-critical part: yfinance estimates are kept strictly
BEFORE the first IBKR payment date and IBKR rows carry everything from there on
— a global "prefer ibkr" switch silently erased every pre-IBKR month from the
dividend card, and keeping estimates inside the IBKR era would double-count the
same dividend from both sources.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.repositories.dividend_repository import DividendRepository
from app.services.dividend_service import DividendService

AS_OF = date(2026, 5, 1)


async def _make_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    session.add(Security(id=1, isin="US0000000001", symbol="AAA", description="Alpha Corp",
                         currency="EUR", conid=100, asset_category="STK", exchange="XETRA"))
    session.add(Security(id=2, isin="US0000000002", symbol="BBB", description="Beta PLC",
                         currency="EUR", conid=200, asset_category="STK", exchange="XETRA"))
    await session.flush()
    return engine, session


async def _seed_payment(session, security_id, on_date, net, source, gross=None, wht="0"):
    await DividendRepository(session).upsert_payment({
        "security_id": security_id,
        "ex_date": on_date,
        "pay_date": on_date,
        "currency": "EUR",
        "shares_held": Decimal("0") if source == "ibkr" else Decimal("10"),
        "gross_amount_eur": Decimal(gross if gross is not None else net),
        "withholding_tax_eur": Decimal(wht),
        "net_amount_eur": Decimal(net),
        "source": source,
    })


def _lot(security_id, open_date, qty, close_date=None):
    return TaxLot(
        security_id=security_id, open_date=open_date, quantity=Decimal(qty),
        cost_basis=Decimal(qty) * 10, cost_basis_eur=Decimal(qty) * 10,
        price_per_unit=Decimal("10"), currency="EUR",
        is_open=close_date is None, close_date=close_date,
    )


@pytest.mark.asyncio
async def test_summary_keeps_pre_ibkr_estimate_months_and_never_sums_the_two():
    engine, session = await _make_session()
    try:
        # Pre-IBKR era: estimates only. IBKR era starts 2026-03-10; an estimate
        # inside that era duplicates the same dividend and must be dropped.
        await _seed_payment(session, 1, date(2025, 5, 12), "7.50", "yfinance_estimate")
        await _seed_payment(session, 1, date(2026, 3, 10), "10.00", "ibkr", gross="12.00", wht="2.00")
        await _seed_payment(session, 1, date(2026, 3, 11), "9.99", "yfinance_estimate")

        summary = await DividendService(session).get_dividend_summary()
        months = {m["month"]: m["amount_eur"] for m in summary["monthly"]}
        assert months["2025-05"] == 7.50           # the old global switch erased this
        assert months["2026-03"] == 10.00          # ibkr only — estimate not added on top
        assert summary["ibkr_from"] == "2026-03-10"
        assert summary["total_net_eur"] == 17.50
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_breakdown_groups_by_month_and_symbol_within_the_year():
    engine, session = await _make_session()
    try:
        await _seed_payment(session, 1, date(2026, 2, 10), "5.00", "ibkr")
        await _seed_payment(session, 2, date(2026, 2, 20), "3.00", "ibkr")
        await _seed_payment(session, 2, date(2025, 11, 5), "4.00", "yfinance_estimate")

        out = await DividendService(session).get_dividend_breakdown(
            year=2026, include_forecast=False, as_of=AS_OF,
        )
        assert out["year"] == 2026
        assert out["years"] == [2025, 2026]
        assert len(out["months"]) == 12            # full axis so chart bars align
        feb = next(m for m in out["months"] if m["month"] == "2026-02")
        assert feb["actual"] == {"AAA": 5.00, "BBB": 3.00}
        assert feb["actual_total_eur"] == 8.00
        assert out["total_net_eur"] == 8.00        # 2025 row filtered out by the year
        rows = {r["symbol"]: r for r in out["securities"]}
        assert rows["AAA"]["payouts"] == 1 and rows["AAA"]["source"] == "ibkr"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_breakdown_projects_a_quarterly_payer_into_future_months_only():
    engine, session = await _make_session()
    try:
        session.add(_lot(1, date(2025, 1, 2), "10"))
        await session.flush()
        for d in (date(2025, 10, 15), date(2026, 1, 15), date(2026, 4, 15)):
            await _seed_payment(session, 1, d, "10.00", "ibkr")

        out = await DividendService(session).get_dividend_breakdown(
            year=2026, include_forecast=True, as_of=AS_OF,
        )
        by_month = {m["month"]: m for m in out["months"]}
        # 2026-04-15 + 91d = 07-15, + 91d = 10-14; both inside the year, after as_of.
        assert by_month["2026-07"]["forecast"] == {"AAA": 10.00}
        assert by_month["2026-10"]["forecast"] == {"AAA": 10.00}
        assert by_month["2026-01"]["forecast"] == {}          # past months never get forecast
        assert by_month["2026-01"]["actual"] == {"AAA": 10.00}
        assert out["total_forecast_net_eur"] == 20.00
        row = out["securities"][0]
        assert row["forecast_payouts"] == 2 and row["payouts"] == 2  # 2026 actuals: Jan + Apr

        off = await DividendService(session).get_dividend_breakdown(
            year=2026, include_forecast=False, as_of=AS_OF,
        )
        assert off["total_forecast_net_eur"] == 0.0
        assert all(m["forecast"] == {} for m in off["months"])
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_sold_position_gets_no_forecast():
    engine, session = await _make_session()
    try:
        session.add(_lot(1, date(2025, 1, 2), "10", close_date=date(2026, 4, 20)))
        await session.flush()
        for d in (date(2025, 10, 15), date(2026, 1, 15), date(2026, 4, 15)):
            await _seed_payment(session, 1, d, "10.00", "ibkr")

        out = await DividendService(session).get_dividend_breakdown(
            year=2026, include_forecast=True, as_of=AS_OF,
        )
        assert out["total_forecast_net_eur"] == 0.0
        assert out["securities"][0]["forecast_payouts"] == 0
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_zero_amount_estimate_rows_are_not_income():
    engine, session = await _make_session()
    try:
        # Computed while no shares were held at the ex-date: net == 0, bookkeeping only.
        await _seed_payment(session, 1, date(2026, 2, 10), "0", "yfinance_estimate")
        out = await DividendService(session).get_dividend_breakdown(
            year=2026, include_forecast=False, as_of=AS_OF,
        )
        assert out["securities"] == []
        assert out["total_net_eur"] == 0.0
    finally:
        await session.close()
        await engine.dispose()
