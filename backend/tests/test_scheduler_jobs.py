"""
Tests for the scheduler's job wiring.

The load-bearing invariant here is a Yahoo Finance one: CLAUDE.md forbids calling
Yahoo without explicit user permission (it rate-limits aggressively, and a full
sync is 50-150+ requests over 730 days). The extra IBKR attempts at 13:00/20:00
exist to recover from transient IBKR errors *without* dragging Yahoo along, so
that separation must not quietly regress into calling the full sync.
"""
from datetime import datetime

import pytest

from app.services.scheduler_service import SchedulerService


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
async def test_scheduler_registers_five_jobs_with_expected_hours():
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
