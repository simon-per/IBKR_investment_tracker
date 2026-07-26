"""
Tests for the offline XML ingest path (`app/cli/ingest_flex_xml.py`).

This path exists because IBKR's Flex Web Service and the Client Portal download button
serve the same statement over independent channels — only the API path spends the token's
request budget, so only it can trip a `Code=1025` lockout. Feeding a downloaded file works
while the token is blocked, and is the only way to reach a prior tax year (our query is
Year-to-Date).

The point of these tests is that the offline route is not a shortcut: it goes through the
same `ingest_flex_statement` as the endpoint and the scheduled jobs, so it must inherit the
empty-statement wipe guard and the idempotent upserts rather than quietly bypassing them.
No network, no credentials.
"""
import re
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.security import Security
from app.models.taxlot import TaxLot
from app.models.trade import Trade
from app.models.dividend_payment import DividendPayment
from app.services.ibkr_service import IBKRService
from app.services.sync_helper import ingest_flex_statement, EmptyStatementError

from tests.test_flex_ingestion_e2e import FLEX_XML, CSU_CONID


async def _make_session():
    """Full schema: ingest_flex_statement touches securities, lots, trades, dividends,
    app_settings and the benchmark cache, so create everything rather than a subset."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, AsyncSession(engine, expire_on_commit=False)


async def _ingest_bytes(session, xml: bytes) -> dict:
    flex_data = IBKRService(token="t", query_id="q").parse_flex_xml(xml)
    result = await ingest_flex_statement(session, flex_data)
    await session.commit()
    return result


@pytest.mark.asyncio
async def test_offline_ingest_populates_everything_the_api_path_would():
    engine, session = await _make_session()
    try:
        result = await _ingest_bytes(session, FLEX_XML)

        assert result["account_id"] == "U1234567"
        assert result["data_to"] == "2026-07-24"
        assert result["securities_synced"] == 1
        assert result["taxlots_synced"] == 1

        # The OPT row and the duplicate ORDER-level row are both excluded, so only the
        # two real stock executions land.
        trades = (await session.execute(select(Trade))).scalars().all()
        assert {t.ib_key for t in trades} == {"TX-G-EXEC", "TX-CSU"}

        # Real withholding, not a yfinance estimate.
        div = (await session.execute(
            select(DividendPayment).where(DividendPayment.source == "ibkr")
        )).scalars().first()
        assert div is not None
        assert div.gross_amount_eur == Decimal("42.50")
        assert div.withholding_tax_eur == Decimal("6.38")

        lot = (await session.execute(select(TaxLot))).scalars().one()
        assert lot.quantity == Decimal("12")
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_re_ingesting_the_same_file_changes_nothing():
    """Re-running must be safe — upserts are keyed on ib_key and isin+exchange."""
    engine, session = await _make_session()
    try:
        await _ingest_bytes(session, FLEX_XML)
        first = {
            "securities": len((await session.execute(select(Security))).scalars().all()),
            "trades": len((await session.execute(select(Trade))).scalars().all()),
            "dividends": len((await session.execute(select(DividendPayment))).scalars().all()),
            "open_lots": len((await session.execute(
                select(TaxLot).where(TaxLot.is_open == True)  # noqa: E712
            )).scalars().all()),
        }

        await _ingest_bytes(session, FLEX_XML)
        second = {
            "securities": len((await session.execute(select(Security))).scalars().all()),
            "trades": len((await session.execute(select(Trade))).scalars().all()),
            "dividends": len((await session.execute(select(DividendPayment))).scalars().all()),
            "open_lots": len((await session.execute(
                select(TaxLot).where(TaxLot.is_open == True)  # noqa: E712
            )).scalars().all()),
        }

        assert first == second, "offline ingest must be idempotent, not additive"
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_wipe_guard_still_fires_through_the_offline_path():
    """
    An empty statement must not be able to mark every holding sold just because it
    arrived as a file rather than over the API. The guard lives in reconcile_taxlots and
    the offline route must inherit it.
    """
    engine, session = await _make_session()
    try:
        await _ingest_bytes(session, FLEX_XML)  # establishes an open lot

        # A real "successful but empty" statement: the section is present but has no rows.
        empty = re.sub(
            rb"<OpenPositions>.*?</OpenPositions>",
            b"<OpenPositions></OpenPositions>",
            FLEX_XML,
            flags=re.DOTALL,
        )

        with pytest.raises(EmptyStatementError):
            await _ingest_bytes(session, empty)

        await session.rollback()
        # The holding survived.
        remaining = (await session.execute(
            select(TaxLot).where(TaxLot.is_open == True)  # noqa: E712
        )).scalars().all()
        assert len(remaining) == 1
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_sold_out_security_gets_linked_through_this_path_too():
    """
    CSU is absent from OpenPositions (fully sold), so the statement's conid map can't
    resolve it. Once the security exists in the DB the trade must still link — this is the
    fix that turned 6 NULL security_id rows into 0.
    """
    engine, session = await _make_session()
    try:
        await _ingest_bytes(session, FLEX_XML)
        csu_trade = (await session.execute(
            select(Trade).where(Trade.ib_key == "TX-CSU")
        )).scalar_one()
        # No CSU security row exists here, so NULL is the correct answer...
        assert csu_trade.security_id is None

        # ...but once it does, a re-ingest links it.
        session.add(Security(
            isin="CA21037X1006", symbol="CSU", description="Constellation Software",
            currency="EUR", conid=int(CSU_CONID), asset_category="STK", exchange="TSE",
        ))
        await session.commit()

        await _ingest_bytes(session, FLEX_XML)
        csu_trade = (await session.execute(
            select(Trade).where(Trade.ib_key == "TX-CSU")
        )).scalar_one()
        assert csu_trade.security_id is not None
    finally:
        await session.close()
        await engine.dispose()
