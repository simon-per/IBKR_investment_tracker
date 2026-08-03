#!/bin/bash
# Unattended deploy for the IBKR portfolio tracker.
#
# Lives here rather than only on the VPS. It governs every deploy, and for months
# the only copy was /root/auto-deploy.sh — unversioned, unreviewed, and invisible
# to anyone reading the repo. Install with:
#
#     install -m 755 ops/auto-deploy.sh /root/auto-deploy.sh
#
# Runs from root's crontab every 10 minutes. deploy.sh is expensive (docker
# compose down + build --no-cache + npm ci), so this only invokes it when
# origin/main is genuinely AHEAD of the checkout — never on an unchanged tick,
# and never when the VPS is ahead (which happens legitimately after a local
# commit here; a bare inequality test would loop-deploy while `git pull` fails).
#
# Deploys unattended, so it also: refuses to start inside a sync window (below),
# backs up the DB first (the container CMD runs `alembic upgrade head`),
# health-checks afterwards, and ROLLS BACK to the previous commit if the app
# doesn't come up.

set -uo pipefail

REPO_DIR="/root/IBKR_investment_tracker"
LOG="/root/auto-deploy.log"
BACKUP_ROOT="/root/ibkr-backups"
HEALTH_URL="http://127.0.0.1:8000/health"
KEEP_BACKUPS=10

# Europe/Berlin hours at which APScheduler runs a sync. This list is a COPY of the
# CronTriggers in backend/app/services/scheduler_service.py, so it can drift — and it
# did: written on 2026-07-31, the same day 13:00 and 20:00 were retired in favour of
# 00:00 and 06:00, it kept the old pair. The effect was the wrong half of the day
# protected: two slots guarded that no longer run, and the two overnight IBKR slots
# guarded by nothing. `tests/test_deploy_guard_hours.py` now reads this file and fails
# the suite if the two ever disagree again.
SYNC_HOURS="0 6 8 15 22"
# Minutes either side of a slot to stay clear of. A rebuild takes ~2-5 minutes and
# APScheduler is in-process, so a deploy overlapping a slot loses that run. The
# persistent job store (2026-08-01) recovers a misfire up to 30 minutes late, so this
# is now a second line of defence rather than the only one — but a `--no-cache` rebuild
# can exceed that grace, so it still earns its keep. 10 covers the rebuild plus the job.
SLOT_MARGIN_MIN=10

log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S') UTC] $*" >> "$LOG"; }

# Never let two deploys overlap.
exec 9>/root/.auto-deploy.lock
flock -n 9 || exit 0

# --- Sync-slot guard ---------------------------------------------------------
# On 2026-07-30 a push landed at 06:00 UTC — exactly the 08:00 Berlin slot — and
# that day's full_sync never ran: no row in sync_runs, no 730-day price refresh,
# no dividend sync, and both IBKR retry slots happened to fail. A deploy is never
# urgent; the next tick is ten minutes away. So skip rather than race.
#
# Deliberately checked before `git fetch`: nothing here should touch the network
# on a tick that cannot deploy anyway.
in_sync_window() {
    local now_h now_m mins_now slot slot_mins delta
    now_h=$(TZ=Europe/Berlin date '+%-H')
    now_m=$(TZ=Europe/Berlin date '+%-M')
    mins_now=$(( now_h * 60 + now_m ))
    for slot in $SYNC_HOURS; do
        slot_mins=$(( slot * 60 ))
        delta=$(( mins_now - slot_mins ))
        [ "$delta" -lt 0 ] && delta=$(( -delta ))
        # Wrap around midnight so 23:55 is measured against 00:00 too.
        [ "$delta" -gt 720 ] && delta=$(( 1440 - delta ))
        if [ "$delta" -le "$SLOT_MARGIN_MIN" ]; then
            echo "$slot"
            return 0
        fi
    done
    return 1
}

if slot=$(in_sync_window); then
    # Only worth a log line when there is actually something waiting to deploy,
    # or this writes a skip every ten minutes forever.
    cd "$REPO_DIR" 2>/dev/null && \
        if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main 2>/dev/null)" ]; then
            log "SKIP: within ${SLOT_MARGIN_MIN}min of the ${slot}:00 Europe/Berlin sync slot; deferring to the next tick"
        fi
    exit 0
fi

cd "$REPO_DIR" || { log "ERROR: $REPO_DIR missing"; exit 1; }

git fetch origin main --quiet 2>>"$LOG" || { log "ERROR: git fetch failed"; exit 1; }

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

[ "$LOCAL" = "$REMOTE" ] && exit 0

# Only deploy when we are strictly BEHIND origin/main (HEAD is its ancestor).
if ! git merge-base --is-ancestor "$LOCAL" "$REMOTE"; then
    log "SKIP: local ${LOCAL:0:7} has diverged from origin/main ${REMOTE:0:7} — needs manual reconcile"
    exit 0
fi

log "change detected: ${LOCAL:0:7} -> ${REMOTE:0:7}, deploying"

# Back up the DB before any migration runs unattended.
BACKUP_DIR="$BACKUP_ROOT/$(date -u +%F)"
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/portfolio.db.autodeploy-$(date -u +%H%M%S)"
if cp "$REPO_DIR/backend/portfolio.db" "$BACKUP" 2>>"$LOG"; then
    log "db backed up -> $BACKUP"
else
    log "WARNING: db backup failed; continuing"
fi

health_ok() {
    for _ in $(seq 1 12); do   # up to ~60s: alembic + uvicorn startup
        [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL")" = "200" ] && return 0
        sleep 5
    done
    return 1
}

if bash "$REPO_DIR/deploy.sh" >>"$LOG" 2>&1 && health_ok; then
    log "SUCCESS: deployed $(git rev-parse --short HEAD), health 200"
else
    log "FAILURE: deploy or health check failed — ROLLING BACK to ${LOCAL:0:7}"
    git reset --hard "$LOCAL" >>"$LOG" 2>&1
    if bash "$REPO_DIR/deploy.sh" >>"$LOG" 2>&1 && health_ok; then
        log "ROLLED BACK to ${LOCAL:0:7}, health 200. origin/main ${REMOTE:0:7} is BROKEN — fix it before it redeploys."
    else
        log "CRITICAL: rollback also failed, app may be DOWN. Manual intervention required."
    fi
fi

# Keep the backup directory from growing without bound.
ls -1t "$BACKUP_ROOT"/*/portfolio.db.autodeploy-* 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs -r rm -f
