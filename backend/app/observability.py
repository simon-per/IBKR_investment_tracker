"""
Request correlation and a last-resort exception handler.

Two gaps this closes.

**An unhandled exception was untraceable.** FastAPI's default handler returns a bare
`{"detail": "Internal Server Error"}` and logs the traceback with nothing tying the two
together, so "the Tax tab 500s" could not be matched to a specific traceback in
`docker compose logs`. Every response now carries an `X-Request-ID`, and the 500 body
repeats it.

**And a leaky one is worse than an opaque one.** `HTTPException` details are already
redacted at the routers, but an *unhandled* exception's string never was. The Flex
token travels as a `t=` URL parameter and `requests` errors stringify with the full
URL — the exact shape that leaked the token into `sync_runs` in 2026-07. So the detail
returned here is a fixed string, and the *logged* message goes through `redact_secrets`
as well: the container log is not public, but it is copied into issues and pasted into
chats, and this repo is public.
"""
import logging
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

from app.redact import redact_secrets

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

# Bound on an inbound id so an upstream proxy (or a caller) cannot use the header as a
# log-injection vector or bloat every log line.
_MAX_INBOUND_ID_LEN = 64


def _request_id(request: Request) -> str:
    """Reuse an inbound id when one is supplied — that is what makes the id correlate
    across a proxy — but only if it is short and plausible."""
    inbound = request.headers.get(REQUEST_ID_HEADER, "").strip()
    if inbound and len(inbound) <= _MAX_INBOUND_ID_LEN and inbound.isprintable():
        return inbound
    return uuid.uuid4().hex[:16]


async def request_id_middleware(request: Request, call_next):
    request_id = _request_id(request)
    # Stashed on state so a handler (and the exception handler below) can read the same
    # id the response will carry.
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")

    logger.exception(
        "Unhandled error [%s] %s %s: %s",
        request_id,
        request.method,
        request.url.path,
        redact_secrets(str(exc)),
    )

    # Deliberately says nothing about the exception. The id is the handle for anyone
    # who can read the logs, and it is useless to anyone who cannot.
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error.",
            "request_id": request_id,
        },
        headers={REQUEST_ID_HEADER: request_id},
    )
