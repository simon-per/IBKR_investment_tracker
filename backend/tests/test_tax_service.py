"""
Tests for TaxService.get_tax_report — dividend income (net of withholding) and
realized capital gains, assembled from the authoritative tables. EUR base so no
FX data is needed. (Holdings snapshot needs market-price tables not created here;
it degrades to empty via the service's guard, which is fine for this test.)
"""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.trade import Trade
from app.models.dividend_payment import DividendPayment
from app.models.app_settings import AppSetting
from app.repositories.trade_repository import TradeRepository
from app.repositories.dividend_repository import DividendRepository
from app.services.tax_service import TaxService


async def _make_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [Security.__table__, TaxLot.__table__, Trade.__table__,
              DividendPayment.__table__, AppSetting.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session = AsyncSession(engine, expire_on_commit=False)
    session.add(Security(
        id=1, isin="US0000000001", symbol="AAA", description="Test Co",
        currency="EUR", conid=100, asset_category="STK", exchange="XETRA",
    ))
    await session.flush()
    return engine, session


@pytest.mark.asyncio
async def test_tax_report_dividends_and_realized_for_year():
    engine, session = await _make_session()
    try:
        # A realized SELL trade in 2025 (EUR): proceeds 200, realized 30 -> cost 170.
        await TradeRepository(session).upsert({
            "ib_key": "TX1", "conid": "100", "security_id": 1, "symbol": "AAA",
            "trade_date": date(2025, 6, 10), "buy_sell": "SELL", "quantity": Decimal("-4"),
            "price": Decimal("50"), "proceeds": Decimal("200"), "commission": Decimal("-1"),
            "currency": "EUR", "realized_pnl": Decimal("30"), "asset_category": "STK",
        })
        # A trade in 2024 must NOT count toward 2025.
        await TradeRepository(session).upsert({
            "ib_key": "TX0", "conid": "100", "security_id": 1, "symbol": "AAA",
            "trade_date": date(2024, 3, 1), "buy_sell": "SELL", "quantity": Decimal("-1"),
            "price": Decimal("10"), "proceeds": Decimal("10"), "commission": Decimal("0"),
            "currency": "EUR", "realized_pnl": Decimal("5"), "asset_category": "STK",
        })
        # An IBKR dividend in 2025: gross 100, withholding 15, net 85.
        await DividendRepository(session).upsert_payment({
            "security_id": 1, "ex_date": date(2025, 5, 2), "pay_date": date(2025, 5, 2),
            "currency": "EUR", "shares_held": Decimal("0"),
            "gross_amount_eur": Decimal("100"), "withholding_tax_eur": Decimal("15"),
            "net_amount_eur": Decimal("85"), "source": "ibkr", "last_computed": datetime.now(),
        })
        await session.commit()

        report = await TaxService(session).get_tax_report(2025)

        assert report["year"] == 2025
        assert report["base_currency"] == "EUR"
        assert report["dividend_source"] == "ibkr"

        assert report["dividend_totals"] == {"gross": 100.0, "withholding": 15.0, "net": 85.0}
        assert len(report["dividend_income"]) == 1

        # Only the 2025 sell counts.
        assert len(report["realized_gains"]) == 1
        assert report["realized_totals"] == {"proceeds": 200.0, "cost_basis": 170.0, "gain_loss": 30.0}

        csv_text = TaxService(session).to_csv(report)
        assert "Dividend income" in csv_text
        assert "Realized capital gains" in csv_text
        assert "AAA" in csv_text
    finally:
        await session.close()
        await engine.dispose()
