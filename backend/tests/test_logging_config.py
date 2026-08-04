"""
`settings.log_level` has to actually configure logging.

It did not. It was read in exactly one place — `echo=settings.log_level == "DEBUG"` for
SQLAlchemy — and nothing called into the logging module, so the root logger kept its
default and Python's last-resort handler emitted WARNING and above only. **Every
`logger.info` in the application was discarded in production**, which was confirmed by
reading the container log: uvicorn's access lines and alembic were there, and not one
line from `app.*`.

That is worse than a missing feature because the documentation assumes otherwise.
CLAUDE.md tells you to grep the container log for a request id, and the scheduler's
`removing retired job` / `kept, next run:` lines — the only direct evidence that job
pruning and misfire recovery work — are INFO. They were unreadable, which is part of why
a job store that had never once opened looked healthy for two days.

A silent no-op setting cannot be caught by reading it, so it is pinned here.

Offline: no network, no app startup.
"""
import logging

import pytest

from app import main
from app.config import settings


@pytest.fixture
def restore_logging():
    """
    Put global logging back exactly as it was.

    `_configure_logging` uses `force=True` (it has to — uvicorn installs handlers before
    the app is imported, and basicConfig is a no-op when any handler exists), so calling
    it in a test would otherwise strip pytest's own capture handler for every test after
    this one.
    """
    root = logging.getLogger()
    saved_level, saved_handlers = root.level, list(root.handlers)
    saved_noisy = {n: logging.getLogger(n).level for n in main._NOISY_AT_INFO}
    yield
    root.setLevel(saved_level)
    root.handlers[:] = saved_handlers
    for name, level in saved_noisy.items():
        logging.getLogger(name).setLevel(level)


def test_an_app_logger_can_actually_emit_info(monkeypatch, restore_logging):
    """The regression itself: INFO from our own modules must reach a handler."""
    monkeypatch.setattr(settings, "log_level", "INFO", raising=False)
    main._configure_logging()

    assert logging.getLogger("app.services.scheduler_service").isEnabledFor(logging.INFO)
    assert logging.getLogger().handlers, "no handler at all — last-resort WARNING only"


def test_a_chatty_provider_library_is_held_back(monkeypatch, restore_logging):
    """
    yfinance narrates every request. A market-data pass is 40 of them across seven passes
    a day, so letting it through at INFO would bury the lines that matter and multiply the
    log volume the compose rotation is sized for.
    """
    monkeypatch.setattr(settings, "log_level", "INFO", raising=False)
    main._configure_logging()

    noisy = logging.getLogger("yfinance")
    assert not noisy.isEnabledFor(logging.INFO)
    assert noisy.isEnabledFor(logging.WARNING), "a real yfinance problem must still show"


def test_debug_turns_our_own_modules_all_the_way_up(monkeypatch, restore_logging):
    monkeypatch.setattr(settings, "log_level", "DEBUG", raising=False)
    main._configure_logging()

    assert logging.getLogger("app").isEnabledFor(logging.DEBUG)
    # ...without dragging the providers along with it.
    assert not logging.getLogger("yfinance").isEnabledFor(logging.INFO)


def test_an_unrecognised_level_falls_back_instead_of_crashing(monkeypatch, restore_logging):
    """
    The value comes from the environment, so a typo in `.env` must not take the container
    down on boot — losing the whole site to a bad log level would be an absurd trade.
    """
    monkeypatch.setattr(settings, "log_level", "chatty", raising=False)
    main._configure_logging()

    assert logging.getLogger("app").isEnabledFor(logging.INFO)


def test_the_setting_is_read_rather_than_ignored(monkeypatch, restore_logging):
    """
    Distinguishes "configured to INFO" from "happens to be INFO by default", which is the
    shape the original bug hid behind — the default and the intended value agreed, so
    nothing looked wrong until you needed a DEBUG line.
    """
    monkeypatch.setattr(settings, "log_level", "ERROR", raising=False)
    main._configure_logging()

    assert not logging.getLogger("app").isEnabledFor(logging.WARNING)
    assert logging.getLogger("app").isEnabledFor(logging.ERROR)
