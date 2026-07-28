"""
Redact the IBKR Flex token from anything that reaches a public surface.

The Flex protocol sends the token as a URL query parameter (`...&t=<token>&q=...`),
and `requests` transport errors stringify with the full request URL — so a plain
`str(e)` from a failed SendRequest carries the token. Those strings used to be
recorded verbatim into `sync_runs.message` and re-served forever by the
unauthenticated `/api/scheduler/status` and `/history` endpoints; production
really did leak the token that way (found and scrubbed 2026-07-28).

Every error string that can be stored in `sync_runs` or returned by a router goes
through `redact_secrets`, and the read path redacts again so rows written before
this module existed (or restored from a backup) cannot leak either.
"""
import re
from typing import Any

from app.config import settings

_REDACTED = "[REDACTED]"

# The `t=` query parameter wherever a URL was stringified into a message. The query
# id (`q=`) is left readable: it is already public in the repo docs and useless
# without the token, and keeping it makes the stored error still debuggable.
_TOKEN_PARAM = re.compile(r"([?&]t=)[^&\s'\"]+")

# Never substring-replace a trivially short token value: a one-letter test token
# would corrupt every message it touches. Real Flex tokens are far longer.
_MIN_TOKEN_LEN = 8


def redact_secrets(value: Any) -> Any:
    """
    Mask the Flex token in a string, or recursively inside dict/list payloads —
    scheduler job results nest step error messages under ``details``. Anything
    else passes through unchanged.
    """
    if isinstance(value, str):
        out = _TOKEN_PARAM.sub(rf"\1{_REDACTED}", value)
        token = getattr(settings, "ibkr_token", "") or ""
        if len(token) >= _MIN_TOKEN_LEN:
            out = out.replace(token, _REDACTED)
        return out
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value
