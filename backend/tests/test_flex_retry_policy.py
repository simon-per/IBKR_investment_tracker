"""
Offline tests for the IBKR Flex download retry policy.

IBKR allows one request per second and 10 per minute per token, and a single
ibflex download() already issues several HTTP requests internally. Retrying
eagerly therefore trips the per-minute cap and then `Code=1025: Too many failed
attempts`, an undocumented lockout that blocks *all* syncing for hours. These
tests pin the policy that prevents that: few attempts, long gaps, and never
retry a lockout. No network — client.download is monkeypatched.
"""
from types import SimpleNamespace

import pytest

from ibflex.client import ResponseCodeError, BadResponseError

from app.services import ibkr_service as ibkr_module
from app.services.ibkr_service import (
    IBKRService,
    FLEX_RETRY_DELAYS_PATIENT,
    _FLEX_RETRY_DELAYS,
)


@pytest.fixture
def no_sleep(monkeypatch):
    """Record backoff durations instead of actually waiting."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(ibkr_module.asyncio, 'sleep', fake_sleep)
    return slept


def _always_raise(monkeypatch, exc):
    calls = {'n': 0}

    def boom(token, query_id):
        calls['n'] += 1
        raise exc

    monkeypatch.setattr(ibkr_module.client, 'download', boom)
    return calls


def test_interactive_budget_is_small():
    """A user-facing sync must not spend the token's per-minute allowance."""
    assert len(_FLEX_RETRY_DELAYS) + 1 == 2
    assert min(_FLEX_RETRY_DELAYS) >= 20


def test_patient_budget_is_spread_out():
    assert all(delay >= 60 for delay in FLEX_RETRY_DELAYS_PATIENT)


@pytest.mark.asyncio
async def test_lockout_1025_is_never_retried(monkeypatch, no_sleep):
    """Retrying a 1025 can extend the lockout, so it must fail on the first hit."""
    calls = _always_raise(
        monkeypatch,
        ResponseCodeError('1025', 'Too many failed attempts. Please review your configuration.'),
    )

    with pytest.raises(RuntimeError, match='temporarily locked'):
        await IBKRService(token='t', query_id='q').fetch_flex_data()

    assert calls['n'] == 1  # no retry
    assert no_sleep == []  # and no backoff wait


@pytest.mark.asyncio
async def test_transient_1001_retries_within_budget(monkeypatch, no_sleep):
    calls = _always_raise(
        monkeypatch,
        ResponseCodeError('1001', 'Statement could not be generated at this time.'),
    )

    with pytest.raises(ResponseCodeError):
        await IBKRService(token='t', query_id='q').fetch_flex_data()

    assert calls['n'] == len(_FLEX_RETRY_DELAYS) + 1
    assert no_sleep == _FLEX_RETRY_DELAYS


@pytest.mark.asyncio
async def test_rate_limit_1018_backs_off_past_the_minute_window(monkeypatch, no_sleep):
    """1018 *is* the per-minute cap, so a short delay would just hit it again."""
    _always_raise(
        monkeypatch,
        ResponseCodeError('1018', 'Too many requests have been made from this token.'),
    )

    with pytest.raises(ResponseCodeError):
        await IBKRService(token='t', query_id='q').fetch_flex_data(retry_delays=[5, 5])

    assert no_sleep == [60, 60]


@pytest.mark.asyncio
async def test_permanent_error_is_not_retried(monkeypatch, no_sleep):
    calls = _always_raise(
        monkeypatch,
        ResponseCodeError('1020', 'Invalid token.'),
    )

    with pytest.raises(ResponseCodeError):
        await IBKRService(token='t', query_id='q').fetch_flex_data()

    assert calls['n'] == 1
    assert no_sleep == []


@pytest.mark.asyncio
async def test_custom_retry_delays_control_attempt_count(monkeypatch, no_sleep):
    # BadResponseError wraps a requests.Response, so hand it something with .content
    calls = _always_raise(monkeypatch, BadResponseError(SimpleNamespace(content=b'')))

    with pytest.raises(BadResponseError):
        await IBKRService(token='t', query_id='q').fetch_flex_data(retry_delays=[1, 2, 3])

    assert calls['n'] == 4
    assert no_sleep == [1, 2, 3]
