"""
The single-flight gate: everything that can reach IBKR or Yahoo shares one
pipeline lock, because two concurrent pipelines racing the Flex budget is the
Code=1025 lockout mechanism, and /api/ is public and unauthenticated.
"""
import pytest

from app.single_flight import SYNC_PIPELINE, SyncBusy, single_flight


def test_the_gate_rejects_a_concurrent_entry_then_releases():
    with single_flight("t-concurrent"):
        with pytest.raises(SyncBusy):
            with single_flight("t-concurrent"):
                pass
    with single_flight("t-concurrent"):
        pass  # released after the block


def test_the_cooldown_rejects_an_immediate_restart():
    with single_flight("t-cooldown", cooldown_seconds=60):
        pass
    with pytest.raises(SyncBusy) as exc:
        with single_flight("t-cooldown", cooldown_seconds=60):
            pass
    assert 0 < exc.value.retry_after_seconds <= 61


def test_no_cooldown_allows_back_to_back_runs():
    for _ in range(3):
        with single_flight("t-sequential"):
            pass


def test_names_are_independent():
    with single_flight("t-a"):
        with single_flight("t-b"):
            pass


def test_the_gate_is_released_when_the_body_raises():
    with pytest.raises(ValueError):
        with single_flight("t-raise"):
            raise ValueError("boom")
    with single_flight("t-raise"):
        pass


@pytest.mark.asyncio
async def test_a_scheduled_job_skips_and_records_when_the_pipeline_is_busy(monkeypatch):
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService()
    recorded = []

    async def _fake_record(result, started_at):
        recorded.append(result)

    monkeypatch.setattr(svc, "_record_run", _fake_record)

    with single_flight(SYNC_PIPELINE):  # a manual run is already in flight
        result = await svc.full_sync_job()

    assert result["status"] == "skipped"
    assert recorded and recorded[0]["type"] == "full_sync"


@pytest.mark.asyncio
async def test_a_manual_trigger_surfaces_busy_instead_of_pretending_success(monkeypatch):
    from app.services.scheduler_service import SchedulerService

    svc = SchedulerService()

    async def _fake_record(result, started_at):
        pass

    monkeypatch.setattr(svc, "_record_run", _fake_record)

    with single_flight(SYNC_PIPELINE):
        with pytest.raises(SyncBusy):
            await svc.trigger_sync_now()


@pytest.mark.asyncio
async def test_the_dividend_card_does_not_start_a_second_yahoo_pass(monkeypatch):
    """
    The 08:00 full_sync runs sync_dividends() too. A dashboard load that finds
    the card stale must not push a second yfinance pass through it.
    """
    import app.routers.dividends as div

    called = []

    class _Boom:
        async def __aenter__(self):
            called.append(1)
            raise AssertionError("dividend sync ran while the pipeline was held")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(div, "AsyncSessionLocal", lambda: _Boom())

    with single_flight(SYNC_PIPELINE):          # a scheduled job owns the pipeline
        await div._run_dividend_sync_background()

    assert not called
    assert div._sync_in_progress is False
