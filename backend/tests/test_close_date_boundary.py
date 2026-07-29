"""
One close-date convention everywhere: a lot sold on D is not held at D's close.

Under the old include-on-close rule a same-day rotation double-counted that day
(the sold lot still 'active on its close date' plus the replacement lot), and a
position sold on 31 December appeared in BOTH the year's Steuerwert snapshot and
its realized gains.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.services.portfolio_service import BaseFx, PortfolioService

D = date(2026, 3, 10)


def _sec(sid, sym):
    return Security(id=sid, isin=f"US000000000{sid}", symbol=sym, description=sym,
                    currency="EUR", conid=100 + sid, asset_category="STK", exchange="XETRA")


def _lot(sid, open_date, qty, cost, close_date=None):
    return TaxLot(
        security_id=sid, open_date=open_date, close_date=close_date,
        is_open=close_date is None, quantity=Decimal(qty),
        cost_basis=Decimal(cost), cost_basis_eur=Decimal(cost),
        price_per_unit=Decimal(cost) / Decimal(qty), currency="EUR",
    )


def test_a_same_day_rotation_counts_once_on_the_rotation_day():
    svc = PortfolioService.__new__(PortfolioService)  # sync helper needs no DB
    sec_a, sec_b = _sec(1, "OLD"), _sec(2, "NEW")
    lots = [
        (_lot(1, date(2025, 6, 1), "10", "100", close_date=D), sec_a),
        (_lot(2, D, "10", "110"), sec_b),
    ]
    price_cache = {1: {D: Decimal("11")}, 2: {D: Decimal("11")}}
    value = svc._calculate_daily_value(
        D, lots, price_cache, {}, price_currency_cache={1: "EUR", 2: "EUR"},
        base_fx=BaseFx("EUR", {}),
    )
    # Only the replacement position exists at D's close — 110, not 220.
    assert value["market_value_eur"] == pytest.approx(110.0)
    assert value["cost_basis_eur"] == pytest.approx(110.0)


@pytest.mark.asyncio
async def test_a_31_dec_sale_is_realized_gains_not_steuerwert():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        year_end = date(2025, 12, 31)
        session.add(_sec(1, "AAA"))
        session.add(_lot(1, date(2025, 2, 3), "10", "100", close_date=year_end))
        session.add(MarketPrice(security_id=1, date=year_end, close_price=Decimal("12"),
                                currency="EUR", source="test"))
        await session.flush()

        svc = PortfolioService(session)
        base_fx = BaseFx("EUR", {})
        snapshot = await svc.holdings_snapshot_as_of(base_fx, year_end)
        realized = await svc.realized_rows_from_closed_lots(
            base_fx, start=date(2025, 1, 1), end=year_end
        )
        assert snapshot == []            # not held at year-end
        assert len(realized) == 1        # the sale lands in realized gains
        assert float(realized[0]["proceeds"]) == pytest.approx(120.0)
    finally:
        await session.close()
        await engine.dispose()
