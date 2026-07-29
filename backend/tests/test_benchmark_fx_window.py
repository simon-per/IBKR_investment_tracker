"""
Two benchmark cache leaks, both offline:

- The FX prefetch tiled the range with `while current <= end: fetch(current);
  current += 30`, leaving up to 29 days uncovered at the tail — the newest
  chart points dropped past the carry-forward window and were recomputed on
  every request, never caching.
- expected_dates counted every weekday, so a market holiday kept the benchmark
  "missing" and every cold request re-hit Yahoo.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.benchmark_price import BenchmarkPrice
from app.services.benchmark_service import BenchmarkService
from app.services.currency_service import CurrencyService


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[BenchmarkPrice.__table__])
        )
    return engine, AsyncSession(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_fx_prefetch_covers_the_range_tail(monkeypatch):
    calls = []

    async def _record(self, from_currency, target_date, to_currency="EUR", days_back=30):
        calls.append((target_date, days_back))

    monkeypatch.setattr(CurrencyService, "_batch_fetch_rates", _record)
    engine, session = await _session()
    try:
        start, end = date(2026, 1, 5), date(2026, 3, 20)  # 74 days: not a 30-multiple
        await BenchmarkService(session)._ensure_fx_rates_available("USD", start, end)

        targets = sorted(t for t, _ in calls)
        assert targets[0] == start          # first chunk covers the lookback buffer
        assert targets[-1] == end           # the tail is covered — this was the hole
        gaps = [(b - a).days for a, b in zip(targets, targets[1:])]
        assert all(g <= 30 for g in gaps)   # no uncovered stretch in between
    finally:
        await session.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_a_settled_benchmark_range_makes_no_yahoo_request(monkeypatch):
    import app.services.benchmark_service as bs

    def _forbidden(*args, **kwargs):
        raise AssertionError("Yahoo must not be called for a settled range")

    monkeypatch.setattr(bs.yf, "Ticker", _forbidden)

    engine, session = await _session()
    try:
        # A full trading week ~3 months back, Thursday missing (a holiday).
        week = [date(2026, 4, 20), date(2026, 4, 21), date(2026, 4, 22), date(2026, 4, 24)]
        for d in week:
            session.add(BenchmarkPrice(ticker="^GSPC", date=d,
                                       close_price=Decimal("5000"), currency="USD"))
        await session.flush()

        fetched = await BenchmarkService(session)._ensure_prices_available(
            "^GSPC", week[0], week[-1], currency="USD"
        )
        assert fetched == 0
    finally:
        await session.close()
        await engine.dispose()
