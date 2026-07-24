"""
Tests for IBKR cash-transaction dividend ingestion (real gross / withholding /
net) in DividendService. Uses EUR amounts so no FX data is required.
"""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  register mappers
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.dividend_payment import DividendPayment
from app.models.app_settings import AppSetting
from app.services.dividend_service import DividendService


async def _make_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    tables = [Security.__table__, TaxLot.__table__, DividendPayment.__table__, AppSetting.__table__]
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session = AsyncSession(engine, expire_on_commit=False)
    session.add(Security(
        id=1, isin="US0000000001", symbol="AAA", description="Test Co",
        currency="EUR", conid=100, asset_category="STK", exchange="XETRA",
    ))
    await session.flush()
    return engine, session


def _ct(ct_type, amount, conid="100", pay_date=date(2026, 5, 2)):
    return {
        "ib_key": f"{ct_type}-{amount}", "conid": conid, "symbol": "AAA",
        "pay_date": pay_date, "type": ct_type, "amount": Decimal(str(amount)),
        "currency": "EUR", "description": "AAA dividend",
    }


@pytest.mark.asyncio
async def test_ibkr_dividend_computes_net_of_withholding():
    engine, session = await _make_session()
    try:
        svc = DividendService(session)
        cash_txns = [_ct("DIVIDEND", 100), _ct("WHTAX", -15)]

        result = await svc.sync_dividends_from_cash_transactions(cash_txns, {"100": 1})
        await session.commit()
        assert result["ibkr_dividends"] == 1

        rows = await svc.repo.get_by_security(1)
        assert len(rows) == 1
        dp = rows[0]
        assert dp.source == "ibkr"
        assert dp.gross_amount_eur == Decimal("100")
        assert dp.withholding_tax_eur == Decimal("15")   # stored positive
        assert dp.net_amount_eur == Decimal("85")

        summary = await svc.get_dividend_summary()
        assert summary["source"] == "ibkr"
        assert summary["total_gross_eur"] == 100.0
        assert summary["total_withholding_eur"] == 15.0
        assert summary["total_net_eur"] == 85.0
        assert summary["total_eur"] == 85.0  # back-compat key is NET
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_ibkr_dividend_aggregates_payment_in_lieu():
    engine, session = await _make_session()
    try:
        svc = DividendService(session)
        # Dividend + payment-in-lieu on the same date sum into gross; withholding applies.
        cash_txns = [_ct("DIVIDEND", 60), _ct("PAYMENTINLIEU", 40), _ct("WHTAX", -15)]

        await svc.sync_dividends_from_cash_transactions(cash_txns, {"100": 1})
        await session.commit()

        rows = await svc.repo.get_by_security(1)
        assert len(rows) == 1
        assert rows[0].gross_amount_eur == Decimal("100")
        assert rows[0].net_amount_eur == Decimal("85")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_empty_cash_transactions_is_noop():
    engine, session = await _make_session()
    try:
        svc = DividendService(session)
        result = await svc.sync_dividends_from_cash_transactions([], {"100": 1})
        assert result["ibkr_dividends"] == 0
        assert await svc.repo.get_by_security(1) == []
    finally:
        await session.close()
        await engine.dispose()
