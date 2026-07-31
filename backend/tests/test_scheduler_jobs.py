"""
Tests for the scheduler's job wiring.

The load-bearing invariant here is a Yahoo Finance one: CLAUDE.md forbids calling
Yahoo without explicit user permission (it rate-limits aggressively, and a full
sync is 50-150+ requests over 730 days). The extra IBKR attempts at 13:00/20:00
exist to recover from transient IBKR errors *without* dragging Yahoo along, so
that separation must not quietly regress into calling the full sync.

Also covers the stale-price detector, which exists because a price that simply never
arrives is otherwise silent: the position is valued at 0.00 and the portfolio total drops
with nothing reporting it (SBI@TSE, -446.93 CHF, 2026-07-27).
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  register all mappers
from app.models.market_price import MarketPrice
from app.models.security import Security
from app.models.taxlot import TaxLot
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.services.scheduler_service import (
    MISFIRE_GRACE_SECONDS,
    STALE_PRICE_DAYS,
    SchedulerService,
    _collect_warnings,
    full_sync_job_entry,
    ibkr_only_sync_job_entry,
    market_data_only_sync_job_entry,
)


class _Spy:
    """Records which sync halves a job invoked."""

    def __init__(self):
        self.called = []

    def make(self, name, result):
        async def fake(*args, **kwargs):
            self.called.append(name)
            return result
        return fake


@pytest.fixture
def spy(monkeypatch):
    s = _Spy()
    svc = SchedulerService()
    monkeypatch.setattr(svc, 'sync_ibkr_data',
                        s.make('ibkr', {"status": "success", "securities_synced": 38}))
    monkeypatch.setattr(svc, 'sync_exchange_rates',
                        s.make('fx', {"status": "success"}))
    monkeypatch.setattr(svc, 'sync_market_data',
                        s.make('market_data', {"status": "success"}))
    monkeypatch.setattr(svc, 'sync_dividends',
                        s.make('dividends', {"status": "success"}))
    monkeypatch.setattr(svc, 'sync_benchmark_prices',
                        s.make('benchmarks', {"status": "success"}))
    return svc, s


@pytest.mark.asyncio
async def test_ibkr_only_job_never_touches_yahoo(spy):
    """The whole point of this job: retry IBKR without spending Yahoo quota."""
    svc, s = spy

    await svc.ibkr_only_sync_job()

    assert 'ibkr' in s.called
    assert 'market_data' not in s.called   # Yahoo — 50-150+ requests
    assert 'dividends' not in s.called     # also yfinance
    assert 'benchmarks' not in s.called    # also yfinance


@pytest.mark.asyncio
async def test_ibkr_only_job_records_its_result_for_the_status_endpoint(spy):
    """/api/scheduler/status (and the cloud validator) read last_sync_result."""
    svc, s = spy

    await svc.ibkr_only_sync_job()

    result = svc.last_sync_result
    assert result["type"] == "ibkr_sync"
    assert result["status"] == "success"
    assert result["ibkr_result"]["securities_synced"] == 38
    datetime.fromisoformat(result["timestamp"])  # parseable


@pytest.mark.asyncio
async def test_ibkr_only_job_reports_failure_status(spy, monkeypatch):
    """A failed IBKR half must surface as status=error, not be masked by FX success."""
    svc, s = spy
    monkeypatch.setattr(svc, 'sync_ibkr_data',
                        s.make('ibkr', {"status": "error", "message": "Code=1025: locked"}))

    await svc.ibkr_only_sync_job()

    assert svc.last_sync_result["status"] == "error"
    assert 'market_data' not in s.called  # still no Yahoo on the failure path


@pytest.mark.asyncio
async def test_a_jobs_warnings_reach_the_top_of_its_result(spy, monkeypatch):
    """_record_run persists result["warnings"], and a job's own dict never had that key —
    so a step's warnings were buried inside `details` and never rendered as warnings."""
    svc, s = spy
    monkeypatch.setattr(svc, 'sync_market_data', s.make('market_data', {
        "status": "success", "warnings": ["SBI@TSE: no cached price at all"],
    }))
    monkeypatch.setattr(svc, '_record_run', lambda *a, **k: _noop())

    await svc.market_data_only_sync_job()

    assert svc.last_sync_result["warnings"] == ["SBI@TSE: no cached price at all"]


async def _noop():
    return None


def test_collect_warnings_merges_steps_and_stays_absent_when_there_are_none():
    merged = {}
    _collect_warnings(merged, {"warnings": ["a"]}, None, {"warnings": ["b"]})
    assert merged["warnings"] == ["a", "b"]

    quiet = {}
    _collect_warnings(quiet, {"status": "success"}, None)
    assert "warnings" not in quiet   # a clean run must not grow an empty list


# --- stale / missing prices ---------------------------------------------------------


@pytest_asyncio.fixture
async def price_db():
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


async def _seed(db, security_id, symbol, latest_price_age=None, is_open=True):
    """A security with one tax lot and, optionally, a newest price N days old."""
    db.add(Security(
        id=security_id, isin=f"US000000000{security_id}", symbol=symbol,
        description=symbol, currency="USD", conid=1000 + security_id,
        asset_category="STK", exchange="NASDAQ",
    ))
    db.add(TaxLot(
        security_id=security_id, open_date=date(2026, 1, 5), quantity=Decimal("10"),
        cost_basis=Decimal("1000"), price_per_unit=Decimal("100"), currency="USD",
        cost_basis_eur=Decimal("900"), is_open=is_open,
        close_date=None if is_open else date(2026, 6, 1),
    ))
    if latest_price_age is not None:
        db.add(MarketPrice(
            security_id=security_id, date=date.today() - timedelta(days=latest_price_age),
            close_price=Decimal("120"), currency="USD", source="yahoo_finance",
        ))
    await db.flush()


@pytest.mark.asyncio
async def test_a_security_with_no_price_at_all_is_reported(price_db):
    """The case that actually cost money: no price means the position is valued at 0.00,
    and every other layer treats that as a legitimate number."""
    await _seed(price_db, 1, "SBI", latest_price_age=None)

    warnings = await SchedulerService().find_stale_priced_securities(price_db)

    assert len(warnings) == 1
    assert "SBI@NASDAQ" in warnings[0]
    assert "no cached price" in warnings[0]


@pytest.mark.asyncio
async def test_a_stale_price_is_reported_with_its_age(price_db):
    await _seed(price_db, 1, "OLD", latest_price_age=STALE_PRICE_DAYS + 3)

    warnings = await SchedulerService().find_stale_priced_securities(price_db)

    assert len(warnings) == 1
    assert f"{STALE_PRICE_DAYS + 3} days old" in warnings[0]


@pytest.mark.asyncio
async def test_a_fresh_price_is_not_reported(price_db):
    """The 13:00 job runs before the US open and the 15:00 one before the US close, so
    a day or two of lag is routine. Warning on it would train the reader to ignore this."""
    await _seed(price_db, 1, "FRESH", latest_price_age=1)

    assert await SchedulerService().find_stale_priced_securities(price_db) == []


@pytest.mark.asyncio
async def test_a_fully_sold_security_going_quiet_is_not_a_fault(price_db):
    """Only open lots move a number the user sees; a closed-out holding legitimately
    stops getting prices, and reporting it would be permanent noise."""
    await _seed(price_db, 1, "GONE", latest_price_age=None, is_open=False)

    assert await SchedulerService().find_stale_priced_securities(price_db) == []


@pytest.mark.asyncio
async def test_each_held_security_is_reported_at_most_once(price_db):
    """Several open lots per security is the norm (972 lots over 38 securities), so the
    grouping has to collapse them or one bad feed becomes dozens of warnings."""
    await _seed(price_db, 1, "MANYLOTS", latest_price_age=None)
    price_db.add(TaxLot(
        security_id=1, open_date=date(2026, 2, 9), quantity=Decimal("5"),
        cost_basis=Decimal("500"), price_per_unit=Decimal("100"), currency="USD",
        cost_basis_eur=Decimal("450"), is_open=True,
    ))
    await price_db.flush()

    warnings = await SchedulerService().find_stale_priced_securities(price_db)

    assert len(warnings) == 1


@pytest.mark.asyncio
async def test_an_old_price_alongside_a_recent_one_is_not_stale(price_db):
    """The check is on the *newest* price, not any price — otherwise every security with
    two years of history would look broken."""
    await _seed(price_db, 1, "HISTORY", latest_price_age=1)
    price_db.add(MarketPrice(
        security_id=1, date=date.today() - timedelta(days=400),
        close_price=Decimal("80"), currency="USD", source="yahoo_finance",
    ))
    await price_db.flush()

    assert await SchedulerService().find_stale_priced_securities(price_db) == []


@pytest.fixture()
def jobstore_url(tmp_path, monkeypatch):
    """A throwaway persistent store per test, so nothing touches the real one."""
    url = f"sqlite:///{tmp_path / 'jobs.db'}"
    monkeypatch.setattr(settings, "scheduler_jobstore_url", url, raising=False)
    return url


@pytest.mark.asyncio
async def test_scheduler_registers_five_jobs_with_expected_hours(jobstore_url):
    # async so AsyncIOScheduler has a running loop to attach to (it only reports
    # itself as running inside one, and shutdown() raises otherwise).
    svc = SchedulerService()
    try:
        svc.start()
        jobs = {job.id: job for job in svc.scheduler.get_jobs()}

        assert set(jobs) == {
            'full_sync_job', 'ibkr_sync_midday', 'ibkr_sync_evening',
            'market_sync_eu_close', 'market_sync_us_close',
        }
        # The two IBKR retries must not collide with the market-data jobs, so that a
        # Yahoo sync and an IBKR sync never run concurrently against the same DB.
        hours = {jid: str(job.trigger) for jid, job in jobs.items()}
        assert "hour='13'" in hours['ibkr_sync_midday']
        assert "hour='20'" in hours['ibkr_sync_evening']
        assert "hour='8'" in hours['full_sync_job']
    finally:
        svc.shutdown()


@pytest.mark.asyncio
async def test_a_missed_slot_is_still_worth_running_for_half_an_hour(jobstore_url):
    """
    A deploy overlapping a Berlin slot used to lose that sync outright — the 08:00
    full_sync on 2026-07-30 went that way. The grace window has to cover a
    `build --no-cache` rebuild and no more: a genuinely long outage must not dump four
    stale slots onto a cold container.
    """
    svc = SchedulerService()
    try:
        svc.start()
        for job in svc.scheduler.get_jobs():
            assert job.misfire_grace_time == MISFIRE_GRACE_SECONDS
            # One catch-up run per job, not one per slot the outage covered.
            assert job.coalesce is True
            assert job.max_instances == 1
    finally:
        svc.shutdown()


@pytest.mark.asyncio
async def test_a_restart_preserves_the_run_time_it_is_meant_to_recover(jobstore_url):
    """
    The trap that makes a persistent store useless: `add_job(replace_existing=True)`
    recomputes next_run_time from now, so the missed timestamp is overwritten on the way
    in and the misfire is never noticed. An unchanged schedule must leave it alone.
    """
    first = SchedulerService()
    first.start()
    before = {j.id: j.next_run_time for j in first.scheduler.get_jobs()}
    first.shutdown()

    second = SchedulerService()
    try:
        second.start()
        after = {j.id: j.next_run_time for j in second.scheduler.get_jobs()}
    finally:
        second.shutdown()

    assert after == before


@pytest.mark.asyncio
async def test_a_schedule_change_still_takes_effect(jobstore_url, monkeypatch):
    """
    The other half: keeping a stored job must not mean a stored job can never be
    rescheduled. Editing an hour has to replace it, stale run time and all.
    """
    first = SchedulerService()
    first.start()
    original = first.scheduler.get_job('full_sync_job').next_run_time
    first.shutdown()

    second = SchedulerService()
    try:
        # Same id, a different hour: the trigger repr differs, so it is replaced.
        real_add_or_keep = SchedulerService._add_or_keep

        def shifted(self, job_id, func, trigger, name):
            if job_id == 'full_sync_job':
                trigger = CronTrigger(hour=9, minute=0, timezone='Europe/Berlin')
            return real_add_or_keep(self, job_id, func, trigger, name)

        monkeypatch.setattr(SchedulerService, "_add_or_keep", shifted)
        second.start()
        job = second.scheduler.get_job('full_sync_job')
        assert "hour='9'" in str(job.trigger)
        assert job.next_run_time != original
    finally:
        second.shutdown()


@pytest.mark.asyncio
async def test_jobs_are_serializable_into_the_persistent_store(jobstore_url):
    """
    The registered targets must be importable by name. They were bound methods, which
    an in-memory store holds happily and a persistent one cannot: pickling
    `self.full_sync_job` drags the live AsyncIOScheduler in with it. A store round-trip
    through a *fresh* service proves the references survive a process boundary.
    """
    first = SchedulerService()
    first.start()
    first.shutdown()

    second = SchedulerService()
    try:
        second.start()
        funcs = {job.id: job.func for job in second.scheduler.get_jobs()}
        assert funcs['full_sync_job'] is full_sync_job_entry
        assert funcs['ibkr_sync_midday'] is ibkr_only_sync_job_entry
        assert funcs['market_sync_us_close'] is market_data_only_sync_job_entry
    finally:
        second.shutdown()


@pytest.mark.asyncio
async def test_an_empty_jobstore_url_keeps_the_scheduler_in_memory(monkeypatch):
    """The escape hatch, so a read-only or ephemeral filesystem can still run."""
    monkeypatch.setattr(settings, "scheduler_jobstore_url", "", raising=False)
    svc = SchedulerService()
    try:
        svc.start()
        assert len(svc.scheduler.get_jobs()) == 5
    finally:
        svc.shutdown()


def test_scheduler_is_enabled_by_default():
    """
    The gate that keeps a local uvicorn from arming real IBKR/Yahoo syncs must
    default to ON, or production silently stops syncing and looks perfectly
    healthy while doing it. Read from the field default rather than the loaded
    settings object, which picks up whatever the local .env says.
    """
    from app.config import Settings

    assert Settings.model_fields["scheduler_enabled"].default is True
