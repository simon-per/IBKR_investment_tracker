"""
Every service that loops securities against Yahoo must abandon the pass on a 429.

Rule 1 in CLAUDE.md is that a rate limit means stop immediately, because continuing is
what turns a short block into a long one. `MarketDataService` was fixed on 2026-08-04
after its "rate-limit detection that aborts the run" turned out to abort only the ticker
*variations* for the security in hand, while the caller moved on to the next of forty.

Three services still had that older shape: `FundamentalsService` (~5 Yahoo endpoints per
security, the most expensive of the four), `AnalystRatingService` and `WatchlistService`
all caught the error, logged it, and continued through the whole list.

**These tests are written against the family, not the instances.** The last one walks the
source for any service that loops and calls Yahoo and asserts it consults the shared
predicate — so a fifth service added later is caught without anyone remembering to
extend this file. That is the lesson CLAUDE.md draws from the same bug appearing twice.

Offline: no network. Every fetch is replaced by a raiser.
"""

import ast
import inspect
import pathlib

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  register all mappers
from app.models.security import Security
from app.models.watchlist_item import WatchlistItem
from app.services.analyst_rating_service import AnalystRatingService
from app.services.fundamentals_service import FundamentalsService
from app.services.watchlist_service import WatchlistService
from app.services.yahoo_rate_limit import is_rate_limit


class RateLimited(Exception):
    """What yfinance raises through when Yahoo refuses us for volume."""

    def __init__(self):
        super().__init__("429 Client Error: Too Many Requests for url: https://query2.finance.yahoo.com")


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
    """
    These loops sleep 1-4s per security and the pacing is not what is under test.

    Zeroing `random.uniform` per service module rather than patching `asyncio.sleep`
    globally: the global patch also intercepts SQLAlchemy's own awaits and fails the
    session with `MissingGreenlet`, which looks like a bug in the code under test.
    """
    for module in (
        "app.services.fundamentals_service",
        "app.services.analyst_rating_service",
        "app.services.watchlist_service",
        "app.services.allocation_service",
        "app.services.dividend_service",
    ):
        monkeypatch.setattr(f"{module}.random.uniform", lambda *_a, **_kw: 0)


async def _seed_securities(db, n=6):
    for i in range(n):
        db.add(Security(
            isin=f"US000000000{i}", symbol=f"SEC{i}", description=f"Security {i}",
            currency="USD", conid=1000 + i, asset_category="STK", exchange="NASDAQ",
        ))
    await db.commit()


# ── The predicate itself ────────────────────────────────────────────────────

def test_the_predicate_recognises_what_yahoo_actually_sends():
    assert is_rate_limit(RateLimited())
    assert is_rate_limit("429 Too Many Requests")
    assert is_rate_limit("Rate limit exceeded")
    assert is_rate_limit("Your request was blocked")


def test_the_predicate_stays_narrow_on_purpose():
    """
    A JSON-decode failure and a 404 are equally what a *bad ticker* looks like, and
    `_try_fetch_yahoo` uses this same verdict to decide whether to keep trying ticker
    variations. Matching them would abort auto-discovery on every security Yahoo does
    not know — a real cost paid on good data, to catch a case the 429 marker already
    covers whenever Yahoo says so plainly.
    """
    assert not is_rate_limit("Expecting value: line 1 column 1 (char 0)")
    assert not is_rate_limit("404 Not Found")
    assert not is_rate_limit("No data found for this date range")
    assert not is_rate_limit(None)
    assert not is_rate_limit("")


# ── Each loop stops ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fundamentals_abandons_the_pass(db, monkeypatch):
    await _seed_securities(db)
    service = FundamentalsService(db)

    calls = []

    async def _raise(ticker):
        calls.append(ticker)
        raise RateLimited()

    monkeypatch.setattr(service, "_fetch_yahoo_data", _raise)
    monkeypatch.setattr(service, "_get_yahoo_ticker", lambda sec, ms=None: _ticker(sec))

    result = await service.sync_fundamentals_data(force_refresh=True)

    assert len(calls) == 1, f"kept fetching after a 429: {calls}"
    assert result["rate_limited"] is True
    assert result["warnings"], "a pass that stopped early must say so"


@pytest.mark.asyncio
async def test_analyst_ratings_abandons_the_pass(db, monkeypatch):
    await _seed_securities(db)
    service = AnalystRatingService(db)

    calls = []

    async def _raise(security):
        calls.append(security.symbol)
        raise RateLimited()

    monkeypatch.setattr(service, "fetch_rating_for_security", _raise)

    result = await service.sync_ratings_for_securities()

    assert len(calls) == 1, f"kept fetching after a 429: {calls}"
    assert result["rate_limited"] is True
    assert result["warnings"]


@pytest.mark.asyncio
async def test_the_watchlist_abandons_the_pass(db, monkeypatch):
    for i in range(5):
        db.add(WatchlistItem(yahoo_ticker=f"TCK{i}"))
    await db.commit()

    service = WatchlistService(db)
    calls = []

    async def _sync_item(ticker, force=False):
        calls.append(ticker)
        # sync_item catches its own fetch failure and returns the message rather than
        # raising, which is exactly why the shared predicate accepts a plain string.
        return {"error": "429 Client Error: Too Many Requests"}

    monkeypatch.setattr(service, "sync_item", _sync_item)

    result = await service.sync_all(force=True)

    assert len(calls) == 1, f"kept fetching after a 429: {calls}"
    assert result["rate_limited"] is True
    assert result["warnings"]


# ── An ordinary failure must NOT stop the pass ──────────────────────────────

@pytest.mark.asyncio
async def test_an_ordinary_error_still_only_skips_one_security(db, monkeypatch):
    """
    The mirror-image bug. One security Yahoo has never heard of must cost that security
    and no more — breaking on every error would let a single delisted ticker suppress
    the whole portfolio's fundamentals indefinitely.
    """
    await _seed_securities(db, n=4)
    service = FundamentalsService(db)

    calls = []

    async def _raise(ticker):
        calls.append(ticker)
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(service, "_fetch_yahoo_data", _raise)
    monkeypatch.setattr(service, "_get_yahoo_ticker", lambda sec, ms=None: _ticker(sec))

    result = await service.sync_fundamentals_data(force_refresh=True)

    assert len(calls) == 4, "an unknown ticker must not abandon the pass"
    assert result["rate_limited"] is False
    assert "warnings" not in result


async def _ticker(security):
    return security.symbol


# ── The family rule ─────────────────────────────────────────────────────────

def test_every_yahoo_looping_service_consults_the_shared_predicate():
    """
    The check that survives a fifth service being added.

    Any service module that both imports yfinance and loops is in this family, and must
    reach the one definition of "rate limited" rather than rolling its own keyword list
    — which is how `market_data_service`'s copy sat alone for months.
    """
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in sorted(list((root / "services").glob("*.py"))):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # An AST import, not the word "yfinance" — three pure helper modules
        # (peg_ratio, safe_numbers, ttm_growth) only mention it in prose, and matching
        # those would make this assertion noise that gets silenced rather than read.
        imports_yahoo = any(
            (isinstance(n, ast.Import) and any(a.name.split(".")[0] == "yfinance" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and (n.module or "").split(".")[0] == "yfinance")
            for n in ast.walk(tree)
        )
        if not imports_yahoo:
            continue
        if "is_rate_limit" not in source:
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} call Yahoo but never consult yahoo_rate_limit.is_rate_limit. "
        "A loop that keeps asking after a 429 is what turns a short block into a long "
        "one — see rule 1 in CLAUDE.md."
    )


def test_nobody_has_reintroduced_a_private_keyword_list():
    """
    Extract, don't sync: a second copy of the marker list is the failure this module was
    created to end, and it would drift silently because both copies keep working.
    """
    services = pathlib.Path(__file__).resolve().parents[1] / "app" / "services"
    offenders = []
    for path in sorted(services.glob("*.py")):
        if path.name == "yahoo_rate_limit.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            # A literal list/tuple of rate-limit markers anywhere but the shared module
            if isinstance(node, (ast.List, ast.Tuple)):
                values = [e.value for e in node.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if any("too many requests" in v.lower() for v in values):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"a private rate-limit marker list reappeared at {offenders}; "
        "import is_rate_limit instead"
    )


def test_the_shared_predicate_is_the_one_market_data_uses():
    """`MarketDataService` is the reference implementation and must not drift back."""
    from app.services import market_data_service

    source = inspect.getsource(market_data_service.MarketDataService._try_fetch_yahoo)
    assert "is_rate_limit" in source


@pytest.mark.asyncio
async def test_two_failures_in_one_pass_do_not_crash_it(db, monkeypatch):
    """
    A pre-existing crash this file's fixtures exposed, separate from the rate limit.

    The handler calls `db.rollback()`, which expires **every** object in the session —
    so the next iteration's `security.symbol` became a lazy refresh, and in async
    SQLAlchemy an expired-attribute load outside an await raises `MissingGreenlet`. That
    read sat *outside* the try, so the second failure of a pass did not cost one
    security: it propagated out of the sync entirely.

    One security Yahoo has no data for is completely ordinary, so this was reachable on
    any pass with two such securities. Each iteration now reloads through an awaited
    `db.get`.
    """
    await _seed_securities(db, n=5)
    service = FundamentalsService(db)

    seen = []

    async def _raise(ticker):
        seen.append(ticker)
        raise ValueError("404 Not Found")

    monkeypatch.setattr(service, "_fetch_yahoo_data", _raise)
    monkeypatch.setattr(service, "_get_yahoo_ticker", lambda sec, ms=None: _ticker(sec))

    result = await service.sync_fundamentals_data(force_refresh=True)

    assert len(seen) == 5, "the pass stopped early on an ordinary error"
    assert result["errors"] == 5
