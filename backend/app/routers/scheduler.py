"""
Scheduler Router
API endpoints for managing the automated sync scheduler.
"""
import logging

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.redact import redact_secrets
from app.repositories.sync_run_repository import SyncRunRepository
from app.services.scheduler_service import get_scheduler

logger = logging.getLogger(__name__)

router = APIRouter()


async def _last_sync(scheduler, db: AsyncSession) -> Optional[Dict]:
    """
    Prefer the in-memory result, fall back to the persisted history.

    The in-memory value is lost on every container restart, and auto-deploy restarts on
    each push — so without this fallback the daily validator can see `last_sync: null`
    and wrongly conclude that no sync ran.
    """
    if scheduler.last_sync_result:
        # In-memory job results carry raw step errors; redact like the stored rows.
        return redact_secrets(scheduler.last_sync_result)
    try:
        run = await SyncRunRepository(db).get_latest()
        return SyncRunRepository.to_dict(run) if run else None
    except Exception as e:  # history is a convenience; never fail the status call
        logger.warning(f"Could not read persisted sync history: {e}")
        return None


@router.post("/trigger", response_model=Dict)
async def trigger_sync_now():
    """
    Manually trigger the daily sync job immediately.

    This endpoint:
    1. Runs IBKR sync immediately
    2. Then runs market data sync
    3. Returns results from both operations

    Useful for testing or manual syncs outside of the scheduled times.

    Returns:
        Summary of sync operations
    """
    try:
        scheduler = get_scheduler()
        result = await scheduler.trigger_sync_now()
        return redact_secrets(result)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=redact_secrets(f"Failed to trigger sync: {str(e)}")
        )


@router.get("/status", response_model=Dict)
async def get_scheduler_status(db: AsyncSession = Depends(get_db)):
    """
    Get the current status of the scheduler, including all jobs and last sync result.

    Returns:
        Information about the scheduler, all scheduled jobs, and last sync result
    """
    try:
        scheduler = get_scheduler()

        if scheduler.scheduler is None:
            return {
                "status": "not_running",
                "message": "Scheduler is not running",
                "jobs": [],
                "last_sync": await _last_sync(scheduler, db),
            }

        jobs = []
        for job in scheduler.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })

        return {
            "status": "running",
            "jobs": jobs,
            "last_sync": await _last_sync(scheduler, db),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=redact_secrets(f"Failed to get scheduler status: {str(e)}")
        )


@router.get("/history", response_model=Dict)
async def get_sync_history(limit: int = 20, db: AsyncSession = Depends(get_db)):
    """
    Recent sync attempts, newest first — the durable record of what ran and what broke.
    """
    try:
        repo = SyncRunRepository(db)
        runs = await repo.get_recent(limit)
        return {"count": len(runs), "runs": [SyncRunRepository.to_dict(r) for r in runs]}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=redact_secrets(f"Failed to read sync history: {str(e)}")
        )
