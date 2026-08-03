"""
The deploy guard's sync hours must match the scheduler's.

`ops/auto-deploy.sh` skips a deploy that would land within `SLOT_MARGIN_MIN` of a
Berlin sync slot, because APScheduler runs in-process and a rebuild overlapping a slot
loses that run. To do that it carries its own copy of the slot hours — a shell variable
that nothing connects to the `CronTrigger`s it is describing.

It drifted, and the drift was the worst possible shape. The guard was written on
2026-07-31, the same day the schedule moved 13:00/20:00 → 00:00/06:00, and it kept the
*old* pair. So from then until 2026-08-03 it guarded two slots that no longer ran and
left the two overnight IBKR slots guarded by nothing at all — protecting exactly the
half of the day that needed no protection.

Nothing could have caught that at runtime: a shell script on the VPS is invisible to
the application. So this test reads the file, the same way
`test_scheduler_jobstore_path.py` reads docker-compose.yml for the same reason.

Offline: filesystem only, no scheduler started, no network.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUTO_DEPLOY = REPO_ROOT / "ops" / "auto-deploy.sh"
SCHEDULER_SERVICE = REPO_ROOT / "backend" / "app" / "services" / "scheduler_service.py"


def _guard_hours() -> set[int]:
    """The hours `ops/auto-deploy.sh` believes it has to stay clear of."""
    match = re.search(r'^SYNC_HOURS="([^"]*)"', AUTO_DEPLOY.read_text(encoding="utf-8"), re.M)
    assert match, "SYNC_HOURS not found in ops/auto-deploy.sh"
    return {int(h) for h in match.group(1).split()}


def _scheduled_hours() -> set[int]:
    """
    The hours the scheduler actually registers.

    Read from the source rather than by starting a scheduler: `SchedulerService.start()`
    arms five jobs against the live Flex token and Yahoo, which is the one thing the
    tests must never risk, and the guard is a claim about the *source* anyway.
    """
    source = SCHEDULER_SERVICE.read_text(encoding="utf-8")
    hours = {
        int(h)
        for h in re.findall(r"CronTrigger\(hour=(\d+),\s*minute=0", source)
    }
    assert hours, "no CronTrigger hours found in scheduler_service.py"
    return hours


@pytest.mark.skipif(not AUTO_DEPLOY.exists(), reason="ops/auto-deploy.sh not present")
def test_deploy_guard_covers_exactly_the_scheduled_slots():
    guard, scheduled = _guard_hours(), _scheduled_hours()

    unguarded = scheduled - guard
    stale = guard - scheduled

    assert not unguarded, (
        f"ops/auto-deploy.sh does not guard {sorted(unguarded)}:00 Europe/Berlin, but the "
        f"scheduler runs a sync then. A deploy landing there loses that run — the "
        f"persistent job store recovers a misfire only within 30 minutes, and a "
        f"--no-cache rebuild can exceed that. Update SYNC_HOURS."
    )
    assert not stale, (
        f"ops/auto-deploy.sh guards {sorted(stale)}:00 Europe/Berlin, but no sync runs "
        f"then. Harmless, but it defers deploys for nothing and hides real drift. "
        f"Update SYNC_HOURS."
    )


@pytest.mark.skipif(not AUTO_DEPLOY.exists(), reason="ops/auto-deploy.sh not present")
def test_the_margin_is_wide_enough_for_a_rebuild():
    """
    `deploy.sh` does `docker compose down`, `build --no-cache` and `npm ci`. Anything
    under a few minutes either side of a slot would let a rebuild straddle it, which is
    the whole failure this guard exists to prevent.
    """
    match = re.search(r"^SLOT_MARGIN_MIN=(\d+)", AUTO_DEPLOY.read_text(encoding="utf-8"), re.M)
    assert match, "SLOT_MARGIN_MIN not found in ops/auto-deploy.sh"
    assert int(match.group(1)) >= 5
