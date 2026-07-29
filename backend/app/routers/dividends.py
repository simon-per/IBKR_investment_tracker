import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.schemas.portfolio import DividendBreakdownResponse
from app.services.dividend_service import DividendService
from app.single_flight import SYNC_PIPELINE, SyncBusy, single_flight

logger = logging.getLogger(__name__)

router = APIRouter()

_sync_in_progress = False

# Auto-refresh tuning for the dividend summary endpoint.
# Data is considered stale if the newest computed payment is older than this.
_STALE_AFTER = timedelta(hours=24)
# Don't auto-trigger more often than this, so repeated card loads within the stale
# window don't enqueue a background task on every request.
_AUTO_SYNC_MIN_INTERVAL = timedelta(hours=6)
_last_auto_sync: Optional[datetime] = None


async def _run_dividend_sync_background() -> None:
    """
    Run dividend sync + compute in background with its own DB session.

    Holds the shared pipeline gate, not just the module flag: the 08:00
    full_sync_job runs sync_dividends() too, and a dashboard load that finds the
    card stale would otherwise start a second yfinance pass straight through it.
    """
    global _sync_in_progress
    try:
        with single_flight(SYNC_PIPELINE):
            _sync_in_progress = True
            try:
                async with AsyncSessionLocal() as db:
                    service = DividendService(db)
                    await service.sync_dividend_data()
                    await service.compute_dividend_income()
            except Exception as e:
                logger.error(f"Background dividend sync failed: {e}")
            finally:
                _sync_in_progress = False
    except SyncBusy as e:
        # A scheduled sync owns the pipeline; the card refreshes after it lands.
        logger.info(f"Dividend sync skipped: {e}")


def _is_summary_stale(summary: dict) -> bool:
    """Stale if there's no data, or the newest computed payment is older than _STALE_AFTER."""
    if not summary.get("monthly"):
        return True
    last_updated = summary.get("last_updated")
    if not last_updated:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(last_updated)) > _STALE_AFTER
    except ValueError:
        return True


@router.get("/summary")
async def get_dividend_summary(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Return dividend summary. Triggers a background sync if data is missing or stale."""
    global _last_auto_sync

    service = DividendService(db)
    summary = await service.get_dividend_summary()
    summary["sync_in_progress"] = _sync_in_progress

    # Auto-refresh when empty or stale, throttled so we don't enqueue on every load.
    if not _sync_in_progress and _is_summary_stale(summary):
        now = datetime.now()
        throttled = _last_auto_sync is not None and (now - _last_auto_sync) < _AUTO_SYNC_MIN_INTERVAL
        if not throttled:
            _last_auto_sync = now
            background_tasks.add_task(_run_dividend_sync_background)
            summary["sync_in_progress"] = True

    return summary


@router.get("/breakdown", response_model=DividendBreakdownResponse)
async def get_dividend_breakdown(
    year: Optional[int] = Query(None, ge=2000, le=2100),
    forecast: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """
    Dividends grouped by month × symbol with per-security totals and optional
    cadence-based forecast projections. Reads only cached data — unlike /summary
    it never enqueues a sync, so it can never touch Yahoo.
    """
    return await DividendService(db).get_dividend_breakdown(
        year=year, include_forecast=forecast
    )


@router.post("/sync")
async def sync_dividends(background_tasks: BackgroundTasks):
    """Manual trigger for dividend sync."""
    if _sync_in_progress:
        return {"status": "already_running", "message": "Dividend sync is already in progress"}
    background_tasks.add_task(_run_dividend_sync_background)
    return {"status": "started", "message": "Dividend sync started in background"}
