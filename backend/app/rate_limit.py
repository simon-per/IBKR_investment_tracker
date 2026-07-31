"""
Per-client request throttle for the public API.

`single_flight` fences the *sync pipelines* — the routes that reach IBKR and Yahoo —
but says nothing about reads, and some reads are expensive: `/api/portfolio/
value-over-time` sweeps up to five years of days across every security, `/api/tax/
report` rebuilds a year-end holdings snapshot, and `/api/portfolio/benchmark` walks a
timeline per benchmark. All of them are anonymous and unmetered behind a public nginx.

This is a fixed-window counter per client, kept deliberately simple:

- **In-process**, like `single_flight`, on the same single-uvicorn-worker assumption.
  A second worker would give each its own window — which loosens the limit rather than
  breaking anything, and the deployment has one worker.
- **Fixed window, not sliding.** A sliding window needs a timestamp deque per client;
  a fixed window needs two integers. The cost is that a client can burst across a
  window boundary, which for a limit whose job is to stop runaway loops is irrelevant.
- **Generous by default.** This must never make the dashboard feel broken: a single
  page load issues a dozen or so requests and a tab switch several more.

Set `RATE_LIMIT_PER_MINUTE=0` to disable it entirely.
"""
import logging
import time
from typing import Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

logger = logging.getLogger(__name__)

# Never throttled: the deploy script polls it, and it exposes nothing.
EXEMPT_PATHS = frozenset({"/health", "/"})

WINDOW_SECONDS = 60

# client key -> (window index, count in that window)
_counters: Dict[str, Tuple[int, int]] = {}

# Bounds the dict against a spray of forged X-Forwarded-For values, which would
# otherwise make the limiter itself the memory leak it exists to prevent. Well above
# any real client count for a single-tenant deployment.
_MAX_TRACKED_CLIENTS = 10_000


def reset() -> None:
    """Drop all counters. For tests — the window state is process-lifetime."""
    _counters.clear()


def client_key(request: Request) -> str:
    """
    Who to count against.

    nginx proxies every request, so `request.client.host` is always the loopback
    address and would make one bucket for the whole internet. The first entry of
    `X-Forwarded-For` is the original client. It is trivially forgeable — but forging
    it only *splits* an attacker's own bucket, so the worst case is the unmetered
    behaviour we have today, while the honest case is correctly limited.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def check(key: str, limit: int, now: Optional[float] = None) -> int:
    """
    Count one request against ``key``.

    Returns 0 when it is allowed, or the seconds remaining in the window when the limit
    is already spent. Counting happens even on rejection so a client that keeps hammering
    does not reset itself.
    """
    if limit <= 0:
        return 0

    now = time.monotonic() if now is None else now
    window = int(now // WINDOW_SECONDS)

    recorded_window, count = _counters.get(key, (window, 0))
    if recorded_window != window:
        recorded_window, count = window, 0

    if count >= limit:
        _counters[key] = (recorded_window, count + 1)
        return int(WINDOW_SECONDS - (now % WINDOW_SECONDS)) + 1

    if key not in _counters and len(_counters) >= _MAX_TRACKED_CLIENTS:
        # Full table and a new client: let it through rather than refusing traffic
        # because of an internal bound. Stale windows are pruned below.
        _prune(window)
        if len(_counters) >= _MAX_TRACKED_CLIENTS:
            return 0

    _counters[key] = (recorded_window, count + 1)
    return 0


def _prune(current_window: int) -> None:
    """Drop counters from a window that has already closed."""
    stale = [k for k, (w, _) in _counters.items() if w != current_window]
    for k in stale:
        del _counters[k]


async def rate_limit_middleware(request: Request, call_next):
    limit = settings.rate_limit_per_minute
    if limit <= 0 or request.url.path in EXEMPT_PATHS:
        return await call_next(request)

    retry_after = check(client_key(request), limit)
    if retry_after:
        logger.warning(
            "Rate limited %s %s (>%d req/min)", request.method, request.url.path, limit
        )
        return JSONResponse(
            status_code=429,
            content={"detail": f"Too many requests. Retry in {retry_after}s."},
            headers={"Retry-After": str(retry_after)},
        )

    return await call_next(request)
