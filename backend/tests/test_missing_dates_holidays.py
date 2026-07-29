"""
get_missing_dates must stop asking Yahoo for market holidays.

A weekday the exchange never traded (July 4th, Good Friday) can never gain a
close price, so it used to stay "missing" forever — and one permanently missing
date makes fetch_and_cache_prices re-request the security's ENTIRE range on
every one of the five daily jobs, indefinitely, against an IP-based rate limit.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.repositories.market_price_repository import MarketPriceRepository

AS_OF = date(2026, 7, 28)

# A Monday..Friday trading week with the Thursday missing (a "holiday"),
# ~3 months before AS_OF — well past the grace window.
WEEK = [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 24)]
HOLIDAY = date(2026, 4, 23)


async def _repo_with(dates):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(
                c, tables=[Security.__table__, MarketPrice.__table__]
            )
        )
    session = AsyncSession(engine, expire_on_commit=False)
    session.add(Security(id=1, isin="US0000000001", symbol="AAA", description="A",
                         currency="EUR", conid=100, asset_category="STK", exchange="XETRA"))
    for d in dates:
        session.add(MarketPrice(security_id=1, date=d, close_price=Decimal("10"),
                                currency="EUR", source="test"))
    await session.flush()
    return engine, session, MarketPriceRepository(session)


@pytest.mark.asyncio
async def test_an_old_interior_hole_is_a_holiday_not_missing():
    engine, session, repo = await _repo_with(WEEK)
    try:
        missing = await repo.get_missing_dates(1, WEEK[0], WEEK[-1], as_of=AS_OF)
        assert HOLIDAY not in missing
        assert missing == []  # the whole week is settled -> no Yahoo request at all
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_recent_interior_hole_is_still_missing():
    # Same shape, but the hole is only a few days old — data may arrive late.
    recent_week = [AS_OF - timedelta(days=7 - i) for i in range(5)]
    recent_week = [d for d in recent_week if d.weekday() < 5]
    hole = recent_week.pop(1)
    engine, session, repo = await _repo_with(recent_week)
    try:
        missing = await repo.get_missing_dates(
            1, min(recent_week), max(recent_week), as_of=AS_OF
        )
        assert hole in missing
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_leading_and_trailing_gaps_stay_missing():
    # Leading = a purge/backfill window; trailing = new days. Both must refetch,
    # no matter how old — that is what heals a split purge.
    engine, session, repo = await _repo_with(WEEK)
    try:
        missing = await repo.get_missing_dates(
            1, WEEK[0] - timedelta(days=4), WEEK[-1] + timedelta(days=4), as_of=AS_OF
        )
        assert any(d < WEEK[0] for d in missing)
        assert any(d > WEEK[-1] for d in missing)
        assert HOLIDAY not in missing
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_an_empty_cache_reports_every_weekday_missing():
    engine, session, repo = await _repo_with([])
    try:
        missing = await repo.get_missing_dates(1, WEEK[0], WEEK[-1], as_of=AS_OF)
        assert missing == [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22),
                           HOLIDAY, date(2026, 4, 24)]
    finally:
        await session.close()
        await engine.dispose()
