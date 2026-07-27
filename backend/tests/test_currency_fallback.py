"""
Offline tests for the secondary FX provider.

Frankfurter republishes the ECB reference rates, so its currency list is fixed at the
ECB's 30 + EUR and will never contain TWD. Buying TSMC on TWSE therefore produced a
currency the app could not convert at all: get_exchange_rate() raised, reconcile_taxlots()
counted the lot in `taxlots_skipped`, and the holding silently disappeared from the
portfolio and the tax report.

The fallback closes that hole, but it serves *current* rates only — there is no free
historical endpoint. These tests pin the resulting rule: recent dates are answered,
older ones still raise so the caller keeps skipping rather than being handed an
invented historical rate.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.exchange_rate import ExchangeRate
from app.services import currency_service as cs
from app.services.currency_service import CurrencyService


# EUR-based snapshot, shaped like open.er-api.com's payload.
FALLBACK_PAYLOAD = {
    "result": "success",
    "base_code": "EUR",
    "rates": {"EUR": 1, "USD": 1.138971, "CHF": 0.930479, "TWD": 36.821601},
}


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[ExchangeRate.__table__])
        )
    db = AsyncSession(engine, expire_on_commit=False)
    try:
        yield db
    finally:
        await db.close()
        await engine.dispose()


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def install_fake_http(monkeypatch, payload=FALLBACK_PAYLOAD, status_code=200):
    """Capture every URL the service requests, answering all of them identically."""
    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, **kwargs):
            calls.append(url)
            return FakeResponse(payload, status_code)

    monkeypatch.setattr(cs.httpx, "AsyncClient", lambda *a, **k: FakeClient())
    return calls


async def _rows(session):
    result = await session.execute(select(ExchangeRate))
    return result.scalars().all()


@pytest.mark.asyncio
async def test_currency_frankfurter_lacks_is_resolved_by_the_fallback(monkeypatch, session):
    calls = install_fake_http(monkeypatch)

    rate = await CurrencyService(session).get_exchange_rate("TWD", date.today())

    # Provider quotes "X per 1 EUR", so TWD->EUR is the reciprocal. The value comes
    # back through the Numeric(18, 8) column, so compare at the column's precision.
    assert abs(rate - Decimal("1") / Decimal("36.821601")) < Decimal("1e-8")
    assert calls == [CurrencyService.FALLBACK_API_URL]

    rows = await _rows(session)
    assert len(rows) == 1
    assert rows[0].from_currency == "TWD"
    assert rows[0].source == CurrencyService.FALLBACK_SOURCE


@pytest.mark.asyncio
async def test_old_date_still_raises_rather_than_backdating_todays_rate(monkeypatch, session):
    """A latest-only provider cannot answer for 2025. Answering anyway would put a
    fabricated historical rate on an old tax lot and the tax report would show it as
    fact, so we keep the skip-with-warning behaviour instead."""
    calls = install_fake_http(monkeypatch)
    stale = date.today() - timedelta(days=CurrencyService.FALLBACK_MAX_AGE_DAYS + 1)

    with pytest.raises(ValueError):
        await CurrencyService(session).get_exchange_rate("TWD", stale)

    assert calls == []          # refused before spending a request
    assert await _rows(session) == []


@pytest.mark.asyncio
async def test_fallback_is_never_consulted_for_a_frankfurter_currency(monkeypatch, session):
    """USD must keep going to Frankfurter — the fallback is a hole-filler, not a
    replacement, and silently switching providers would change every cached rate."""
    calls = install_fake_http(monkeypatch, payload={"rates": {}})

    with pytest.raises(ValueError):
        await CurrencyService(session).get_exchange_rate("USD", date.today())

    assert calls, "expected Frankfurter to be queried"
    assert all(CurrencyService.FALLBACK_API_URL not in url for url in calls)


@pytest.mark.asyncio
async def test_carry_forward_preserves_the_provider_tag(monkeypatch, session):
    """A rate carried across a weekend must not be relabelled as Frankfurter data."""
    install_fake_http(monkeypatch, payload={"result": "error"})
    yesterday = date.today() - timedelta(days=1)
    session.add(ExchangeRate(
        date=yesterday, from_currency="TWD", to_currency="EUR",
        rate=Decimal("0.02716"), source=CurrencyService.FALLBACK_SOURCE,
    ))
    await session.flush()

    rate = await CurrencyService(session).get_exchange_rate("TWD", date.today())

    assert rate == Decimal("0.02716")
    carried = [r for r in await _rows(session) if r.date == date.today()]
    assert len(carried) == 1
    assert carried[0].source == CurrencyService.FALLBACK_SOURCE


@pytest.mark.asyncio
async def test_provider_failure_leaves_the_cache_untouched(monkeypatch, session):
    """The fetcher must never raise on its own; get_exchange_rate() owns that decision."""
    install_fake_http(monkeypatch, payload={"result": "error"})

    with pytest.raises(ValueError):
        await CurrencyService(session).get_exchange_rate("TWD", date.today())

    assert await _rows(session) == []
