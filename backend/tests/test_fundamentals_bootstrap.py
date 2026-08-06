"""
`sync_stale_fundamentals` has to be able to fetch a security for the first time.

It pre-filtered on `get_stale_metrics(days_old=1)` and bailed when that came back empty.
That query selects metrics rows which already **exist**, so a security with no row was
invisible to it — and whenever every existing row happened to be fresh, this path reported
"No stale fundamentals to update" and a newly-bought security never acquired fundamentals
through it at all. The union that would have caught it (`s.id not in existing_ids or
s.id in stale_ids`) sat one call *below* the guard that stopped it being reached.

The reason this survived is worth pinning too: `sync_stale_ratings` was fixed for exactly
this shape, and both its docstring and CLAUDE.md's duplicated-logic table cite *this*
method as the sibling that "already unions the two sets". Both were describing the inner
function while the entry point pre-filtered — a correct fix justified by a false reading
of the code it was copying. `tests/test_analyst_rating_bootstrap.py` is the mirror of this
file, and its own opening paragraph repeats the claim.

Offline: `_fetch_yahoo_data` is faked, so yfinance is never reached.
"""
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.clock import utcnow
from app.database import Base
import app.models  # noqa: F401  register all mappers
from app.models.fundamental_metrics import FundamentalMetrics
from app.models.security import Security
from app.services import fundamentals_service as fs_mod
from app.services.fundamentals_service import FundamentalsService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


@pytest.fixture(autouse=True)
def _no_delays(monkeypatch):
    async def _sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(fs_mod.asyncio, "sleep", _sleep)
    monkeypatch.setattr(fs_mod.random, "uniform", lambda *_a: 0)


def add_security(session, security_id: int, symbol: str) -> Security:
    security = Security(
        id=security_id, isin=f"US000000000{security_id}", symbol=symbol,
        description=symbol, currency="USD", conid=security_id,
        asset_category="STK", exchange="NASDAQ",
    )
    session.add(security)
    return security


def add_metrics(session, security_id: int, age_days: int) -> FundamentalMetrics:
    metrics = FundamentalMetrics(
        security_id=security_id, trailing_pe=20.0, quote_type="EQUITY",
        last_updated=utcnow() - timedelta(days=age_days),
    )
    session.add(metrics)
    return metrics


@pytest.fixture
def fetched(monkeypatch):
    """Record which securities were fetched, without touching yfinance."""
    seen = []

    def _fake_fetch(_self, ticker):
        seen.append(ticker)
        return {}, None, None, None, None

    monkeypatch.setattr(FundamentalsService, "_fetch_yahoo_data", _fake_fetch)
    return seen


@pytest.mark.asyncio
async def test_a_security_with_no_metrics_row_is_picked_up(db, fetched):
    """The bug: the stale query cannot see a security that has no row to be stale."""
    add_security(db, 1, "NEW")
    await db.commit()

    result = await FundamentalsService(db).sync_stale_fundamentals()

    assert fetched, "a never-synced security was never fetched"
    assert result["message"] != "No stale fundamentals to update"


@pytest.mark.asyncio
async def test_a_fresh_table_still_bootstraps_a_new_security(db, fetched):
    """
    The precise failure, and the one production was one fundamentals run away from: every
    existing row is fresh, so the old pre-filter returned empty and bailed — while a
    newly-bought security sat there with no row at all.
    """
    add_security(db, 1, "OLD")
    add_security(db, 2, "NEW")
    add_metrics(db, 1, age_days=0)          # fresh, so `get_stale_metrics` finds nothing
    await db.commit()

    await FundamentalsService(db).sync_stale_fundamentals()

    assert fetched == ["NEW"], f"expected only the unsynced security, got {fetched}"


@pytest.mark.asyncio
async def test_a_stale_row_is_still_refreshed(db, fetched):
    """The direction that must not regress — dropping the guard must not stop refreshes."""
    add_security(db, 1, "OLD")
    add_metrics(db, 1, age_days=5)
    await db.commit()

    await FundamentalsService(db).sync_stale_fundamentals()

    assert fetched == ["OLD"]


@pytest.mark.asyncio
async def test_an_all_fresh_portfolio_still_reports_nothing_to_do(db, fetched):
    """
    And the other direction: with every security synced and fresh, this must not start
    spending ~5 Yahoo requests per security on every call. The delegate's own early
    return covers it, which is why the guard was removable rather than replaceable.
    """
    add_security(db, 1, "AAA")
    add_metrics(db, 1, age_days=0)
    await db.commit()

    result = await FundamentalsService(db).sync_stale_fundamentals()

    assert fetched == []
    assert result["securities_processed"] == 0
    assert result["message"] == "All fundamentals are up to date"
