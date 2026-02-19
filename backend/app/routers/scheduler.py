"""
Scheduler Router
API endpoints for managing the automated sync scheduler.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict

from app.services.scheduler_service import get_scheduler


router = APIRouter()


@router.post("/trigger", response_model=Dict)
async def trigger_sync_now():
    """
    Manually trigger the daily sync job immediately.

    This endpoint:
    1. Runs IBKR sync immediately
    2. Then runs market data sync
    3. Returns results from both operations

    Useful for testing or manual syncs outside of the scheduled 4 PM time.

    Returns:
        Summary of sync operations
    """
    try:
        scheduler = get_scheduler()
        result = await scheduler.trigger_sync_now()
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger sync: {str(e)}"
        )


@router.get("/status", response_model=Dict)
async def get_scheduler_status():
    """
    Get the current status of the scheduler.

    Returns:
        Information about the scheduler and next scheduled run
    """
    try:
        scheduler = get_scheduler()

        if scheduler.scheduler is None:
            return {
                "status": "not_running",
                "message": "Scheduler is not running"
            }

        # Get the daily sync job
        job = scheduler.scheduler.get_job('daily_sync_job')

        if job is None:
            return {
                "status": "error",
                "message": "Daily sync job not found"
            }

        return {
            "status": "running",
            "job_name": job.name,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get scheduler status: {str(e)}"
        )
