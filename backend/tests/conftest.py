"""
Shared test setup.

The middleware added in `app/main.py` keeps **process-lifetime** state — the rate
limiter's per-client window counters — and reads production defaults from `settings`.
Both leak across tests: a module that drives the HTTP stack hundreds of times inside
one minute would start seeing 429s from requests an earlier module made, and the
failure would move around as tests were reordered.

So every test runs with the limiter off and write auth off, i.e. the behaviour the
suite was written against. `tests/test_api_hardening.py` re-enables them explicitly,
which is the only place their behaviour is the thing under test.
"""
import pytest

from app import rate_limit
from app.config import settings


@pytest.fixture(autouse=True)
def _neutral_middleware_state(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0, raising=False)
    monkeypatch.setattr(settings, "api_admin_token", "", raising=False)
    rate_limit.reset()
    yield
    rate_limit.reset()
