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

    Useful for testing or manual syncs outside of the scheduled times.

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
                "last_sync": None,
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
            "last_sync": scheduler.last_sync_result,
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get scheduler status: {str(e)}"
        )
