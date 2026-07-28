"""
The Flex token travels as a URL query parameter, and `requests` transport errors
stringify with the full request URL — so any recorded or returned `str(e)` can
carry the token. Production served it through the public /api/scheduler/history
until 2026-07-28. These tests pin both choke points: what gets stored is clean,
and what gets read out is clean even when a poisoned row already exists.
"""
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401
from app.models.sync_run import SyncRun
from app.redact import redact_secrets
from app.repositories.sync_run_repository import SyncRunRepository

FAKE_TOKEN = "123456789012345678901234"
POISONED = (
    "Failed to sync IBKR data: HTTPSConnectionPool(host='gdcdyn.interactivebrokers.com', "
    "port=443): Max retries exceeded with url: /Universal/servlet/FlexStatementService."
    f"SendRequest?v=3&t={FAKE_TOKEN}&q=1389408 "
    f"(Caused by NameResolutionError(url: ...?v=3&t={FAKE_TOKEN}&q=1389408))"
)


def test_token_param_is_masked_everywhere_but_query_id_survives():
    out = redact_secrets(POISONED)
    assert FAKE_TOKEN not in out
    assert out.count("&t=[REDACTED]") == 2  # the URL appears twice in a chained error
    assert "&q=1389408" in out  # query id is public and keeps the message debuggable


def test_literal_token_value_is_masked_outside_url_shapes(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ibkr_token", FAKE_TOKEN)
    out = redact_secrets(f"token {FAKE_TOKEN} appeared bare in a log line")
    assert FAKE_TOKEN not in out


def test_a_short_token_is_never_substring_replaced(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ibkr_token", "t")
    assert redact_secrets("the letter t stays intact") == "the letter t stays intact"


def test_redaction_recurses_into_job_result_payloads():
    payload = {
        "status": "error",
        "details": {"ibkr": {"message": POISONED}, "taxlots": 975},
        "warnings": [POISONED],
    }
    out = redact_secrets(payload)
    assert FAKE_TOKEN not in str(out)
    assert out["details"]["taxlots"] == 975
    assert redact_secrets(None) is None


@pytest.mark.asyncio
async def test_record_never_stores_a_token_bearing_string():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = AsyncSession(engine, expire_on_commit=False)
    try:
        run = await SyncRunRepository(session).record(
            sync_type="ibkr", status="error", message=POISONED,
            details={"step": POISONED}, warnings=[POISONED],
        )
        assert run is not None
        stored = f"{run.message} {run.details} {run.warnings}"
        assert FAKE_TOKEN not in stored
        assert "&t=[REDACTED]" in run.message
    finally:
        await session.close()
        await engine.dispose()


def test_to_dict_redacts_rows_written_before_the_fix():
    poisoned_row = SyncRun(
        sync_type="ibkr", status="error", message=POISONED,
        details={"step": POISONED}, warnings=[POISONED],
        started_at=None, finished_at=None,
    )
    out = SyncRunRepository.to_dict(poisoned_row)
    assert FAKE_TOKEN not in str(out)
    assert "&t=[REDACTED]" in out["message"]
