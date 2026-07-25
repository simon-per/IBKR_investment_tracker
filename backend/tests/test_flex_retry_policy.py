"""
Offline tests for the IBKR Flex download retry policy.

IBKR allows one request per second and 10 per minute per token, and a single
ibflex download() already issues several HTTP requests internally. Retrying
eagerly therefore trips the per-minute cap and then `Code=1025: Too many failed
attempts`, an undocumented lockout that blocks *all* syncing for hours. These
tests pin the policy that prevents that: few attempts, long gaps, never retry a
lockout, and — most importantly — never re-issue SendRequest just because the
statement isn't ready yet. No network: ibflex's client functions are monkeypatched.
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
    """
    Fail at step 1 (SendRequest). That's the only step the outer retry loop may
    re-issue, so patching it here is what exercises that budget — and it keeps the
    tests offline now that fetch_flex_data drives the 2-step protocol itself rather
    than calling client.download().
    """
    calls = {'n': 0}

    def boom(token, query_id):
        calls['n'] += 1
        raise exc

    monkeypatch.setattr(ibkr_module.client, 'request_statement', boom)
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


#
# The 2-step protocol: SendRequest once, then poll the SAME reference code.
#

class _FakeFlexServer:
    """
    Stands in for IBKR's two endpoints. `retrieve_results` is consumed one per poll;
    each item is either an exception to raise or a bytes payload to return.
    """

    def __init__(self, retrieve_results):
        self.retrieve_results = list(retrieve_results)
        self.request_calls = 0
        self.retrieve_calls = 0

    def install(self, monkeypatch):
        def request_statement(token, query_id):
            self.request_calls += 1
            return SimpleNamespace(ReferenceCode="REF123", Url=None)

        def submit_request(url, token, query):
            self.retrieve_calls += 1
            assert query == "REF123", "must poll the same reference code"
            outcome = self.retrieve_results.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(content=outcome)

        monkeypatch.setattr(ibkr_module.client, 'request_statement', request_statement)
        monkeypatch.setattr(ibkr_module.client, 'submit_request', submit_request)
        # check_statement_response only sees successful payloads here; pending states are
        # delivered as ResponseCodeError from submit_request, matching ibflex's behaviour.
        monkeypatch.setattr(ibkr_module.client, 'check_statement_response', lambda r: True)
        monkeypatch.setattr(ibkr_module.time, 'sleep', lambda s: None)
        return self


def test_not_ready_statement_is_re_retrieved_never_re_requested(monkeypatch):
    """
    THE regression this refactor exists for. IBKR: "you should not re-initiate the Flex
    request, but instead keep trying to retrieve the statement." A 1001 while polling
    must NOT start a second generation job — that is what earned two 1025 lockouts.
    """
    server = _FakeFlexServer([
        ResponseCodeError('1001', 'Statement could not be generated at this time.'),
        ResponseCodeError('1019', 'Statement generation in progress.'),
        b'<FlexQueryResponse></FlexQueryResponse>',
    ]).install(monkeypatch)

    data = IBKRService(token='t', query_id='q')._download_statement(60)

    assert data == b'<FlexQueryResponse></FlexQueryResponse>'
    assert server.request_calls == 1        # <-- the whole point
    assert server.retrieve_calls == 3


def test_lockout_during_retrieve_is_not_retried(monkeypatch):
    server = _FakeFlexServer([
        ResponseCodeError('1025', 'Too many failed attempts. Please review your configuration.'),
    ]).install(monkeypatch)

    with pytest.raises(RuntimeError, match='temporarily locked'):
        IBKRService(token='t', query_id='q')._download_statement(60)

    assert server.request_calls == 1
    assert server.retrieve_calls == 1  # gave up immediately


def test_fatal_code_during_retrieve_does_not_re_request(monkeypatch):
    """An invalid token mid-poll is terminal; don't start another generation job."""
    server = _FakeFlexServer([
        ResponseCodeError('1015', 'Token is invalid.'),
    ]).install(monkeypatch)

    with pytest.raises(ResponseCodeError):
        IBKRService(token='t', query_id='q')._download_statement(60)

    assert server.request_calls == 1


def test_retrieve_gives_up_at_the_deadline(monkeypatch):
    """A statement that never becomes ready must time out, not poll forever."""
    server = _FakeFlexServer(
        [ResponseCodeError('1001', 'not ready')] * 500
    ).install(monkeypatch)

    with pytest.raises(TimeoutError, match='still not ready'):
        IBKRService(token='t', query_id='q')._download_statement(1)

    assert server.request_calls == 1
    assert server.retrieve_calls < 500  # stopped early


@pytest.mark.asyncio
async def test_custom_retry_delays_control_attempt_count(monkeypatch, no_sleep):
    # BadResponseError wraps a requests.Response, so hand it something with .content
    calls = _always_raise(monkeypatch, BadResponseError(SimpleNamespace(content=b'')))

    with pytest.raises(BadResponseError):
        await IBKRService(token='t', query_id='q').fetch_flex_data(retry_delays=[1, 2, 3])

    assert calls['n'] == 4
    assert no_sleep == [1, 2, 3]
