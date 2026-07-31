"""
The middleware stack: write auth, the per-client rate limit, request ids.

Exercised through the real HTTP stack rather than by calling the functions, because
what matters is the *order and scope* of the layers — that reads stay open, that a
new mutating route is covered without anyone remembering to annotate it, and that a
rejection still carries a correlation id.

No database is touched: every assertion here lands on a middleware before a handler
runs, or on /health, which has no dependencies.
"""
import pytest
from fastapi.testclient import TestClient

from app import rate_limit
from app.auth import API_KEY_HEADER, MUTATING_METHODS
from app.config import settings
from app.main import app
from app.observability import REQUEST_ID_HEADER

TOKEN = "test-admin-token-long-enough"


@pytest.fixture()
def client(monkeypatch):
    # The limiter is process-lifetime state; a leftover window would make these flaky.
    rate_limit.reset()
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0, raising=False)
    monkeypatch.setattr(settings, "api_admin_token", "", raising=False)
    yield TestClient(app)
    rate_limit.reset()


# ── write auth ────────────────────────────────────────────────────────────────

def test_disabled_by_default_so_enabling_it_is_a_deliberate_act(client):
    """
    The whole point of the default. An existing deployment must not start 401-ing
    because a new version shipped — turning this on is a decision, not a side effect.
    """
    assert settings.api_admin_token == ""
    # 404 rather than 401: the middleware let it through and no such route exists.
    assert client.post("/api/does-not-exist").status_code == 404


def test_health_reports_whether_write_auth_is_on(client, monkeypatch):
    assert client.get("/health").json()["write_auth_enabled"] is False
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    assert client.get("/health").json()["write_auth_enabled"] is True


def test_a_mutating_request_without_a_key_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)

    r = client.put("/api/settings/base-currency", json={"base_currency": "USD"})
    assert r.status_code == 401
    assert API_KEY_HEADER in r.json()["detail"]
    # A generic client is told how to authenticate rather than left to guess.
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


def test_a_wrong_key_is_refused(client, monkeypatch):
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    r = client.delete("/api/watchlist/1", headers={API_KEY_HEADER: "wrong"})
    assert r.status_code == 401


def test_a_prefix_of_the_key_is_refused(client, monkeypatch):
    """compare_digest, not `==` — and not `startswith` either."""
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    r = client.delete("/api/watchlist/1", headers={API_KEY_HEADER: TOKEN[:-1]})
    assert r.status_code == 401


def test_the_key_passes_the_request_through(client, monkeypatch):
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    r = client.post("/api/does-not-exist", headers={API_KEY_HEADER: TOKEN})
    assert r.status_code == 404  # reached routing, so auth allowed it


def test_a_bearer_token_is_accepted_too(client, monkeypatch):
    """curl and CI reach for Authorization; the browser sends X-API-Key."""
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    r = client.post("/api/does-not-exist", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 404


def test_reads_stay_open_because_the_ui_has_no_login(client, monkeypatch):
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    for path in ("/health", "/api/settings", "/api/portfolio/benchmarks"):
        assert client.get(path).status_code == 200, path


def test_health_stays_reachable_for_the_deploy_script(client, monkeypatch):
    """It is polled by deploy.sh and any uptime check, and exposes no data."""
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    assert client.get("/health").status_code == 200


def test_every_mutating_route_is_covered_without_being_annotated(client, monkeypatch):
    """
    The reason this is middleware and not a per-route dependency: the guard keys on the
    HTTP method, so a route added later is protected the moment it exists. This walks
    the live route table rather than a hand-kept list, so a new POST fails here if the
    scoping ever narrows.
    """
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)

    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or "{" in path:
            continue
        for method in sorted(set(getattr(route, "methods", set())) & MUTATING_METHODS):
            # No key: must be refused before the handler can do anything.
            assert client.request(method, path).status_code == 401, f"{method} {path}"
            checked += 1

    assert checked >= 10, f"expected the mutating surface to be substantial, saw {checked}"


# ── rate limiting ─────────────────────────────────────────────────────────────

def test_zero_disables_the_limiter(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0, raising=False)
    for _ in range(50):
        assert client.get("/api/portfolio/benchmarks").status_code == 200


def test_the_limit_answers_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3, raising=False)
    headers = {"X-Forwarded-For": "203.0.113.7"}

    for _ in range(3):
        assert client.get("/api/portfolio/benchmarks", headers=headers).status_code == 200

    r = client.get("/api/portfolio/benchmarks", headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_clients_are_counted_separately(client, monkeypatch):
    """
    nginx proxies everything, so request.client.host is always loopback — without
    reading X-Forwarded-For there would be one bucket for the whole internet.
    """
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2, raising=False)

    for _ in range(2):
        client.get("/api/portfolio/benchmarks", headers={"X-Forwarded-For": "198.51.100.1"})
    assert client.get(
        "/api/portfolio/benchmarks", headers={"X-Forwarded-For": "198.51.100.1"}
    ).status_code == 429
    assert client.get(
        "/api/portfolio/benchmarks", headers={"X-Forwarded-For": "198.51.100.2"}
    ).status_code == 200


def test_health_is_never_throttled(client, monkeypatch):
    """The deploy script polls it in a loop; throttling it would fail deploys."""
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1, raising=False)
    for _ in range(10):
        assert client.get("/health").status_code == 200


def test_a_rejected_request_still_counts_against_the_window():
    """Otherwise a client that keeps hammering resets its own limit."""
    rate_limit.reset()
    for _ in range(3):
        assert rate_limit.check("k", limit=3, now=0.0) == 0
    assert rate_limit.check("k", limit=3, now=0.0) > 0
    # Still refused at the end of the window despite the extra attempts.
    assert rate_limit.check("k", limit=3, now=59.0) > 0
    # A fresh window clears it.
    assert rate_limit.check("k", limit=3, now=61.0) == 0


def test_the_forwarded_header_is_bounded(client, monkeypatch):
    """A long forged value must not become a long dictionary key."""
    monkeypatch.setattr(settings, "rate_limit_per_minute", 5, raising=False)
    client.get("/api/portfolio/benchmarks", headers={"X-Forwarded-For": "9" * 500})
    assert all(len(k) <= 64 for k in rate_limit._counters)


# ── request ids ───────────────────────────────────────────────────────────────

def test_every_response_carries_a_request_id(client):
    r = client.get("/health")
    assert r.headers[REQUEST_ID_HEADER]
    assert r.json()["request_id"] == r.headers[REQUEST_ID_HEADER]


def test_ids_differ_between_requests(client):
    a = client.get("/health").headers[REQUEST_ID_HEADER]
    b = client.get("/health").headers[REQUEST_ID_HEADER]
    assert a != b


def test_an_inbound_id_is_reused_so_it_correlates_across_a_proxy(client):
    r = client.get("/health", headers={REQUEST_ID_HEADER: "upstream-abc123"})
    assert r.headers[REQUEST_ID_HEADER] == "upstream-abc123"


def test_an_implausible_inbound_id_is_replaced(client):
    """Bounded, so the header cannot be a log-injection vector or bloat every line."""
    r = client.get("/health", headers={REQUEST_ID_HEADER: "x" * 500})
    assert r.headers[REQUEST_ID_HEADER] != "x" * 500
    assert len(r.headers[REQUEST_ID_HEADER]) <= 64


def test_a_rejected_request_is_still_correlatable(client, monkeypatch):
    """
    The request-id layer sits outermost, so the 401 and 429 the layers below produce
    carry one too — otherwise the responses hardest to debug are the ones with no handle.
    """
    monkeypatch.setattr(settings, "api_admin_token", TOKEN, raising=False)
    assert client.post("/api/sync/ibkr").headers[REQUEST_ID_HEADER]

    monkeypatch.setattr(settings, "api_admin_token", "", raising=False)
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1, raising=False)
    headers = {"X-Forwarded-For": "192.0.2.99"}
    client.get("/api/portfolio/benchmarks", headers=headers)
    refused = client.get("/api/portfolio/benchmarks", headers=headers)
    assert refused.status_code == 429
    assert refused.headers[REQUEST_ID_HEADER]
