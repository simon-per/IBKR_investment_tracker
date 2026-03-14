import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.services.dividend_service import DividendService

logger = logging.getLogger(__name__)

router = APIRouter()

_sync_in_progress = False


async def _run_dividend_sync_background() -> None:
    """Run dividend sync + compute in background with its own DB session."""
    global _sync_in_progress
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


@router.get("/summary")
async def get_dividend_summary(
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Return dividend summary. Triggers background sync if data is stale."""
    service = DividendService(db)
    summary = await service.get_dividend_summary()
    summary["sync_in_progress"] = _sync_in_progress

    # If no data or stale, trigger background sync
    if not summary["monthly"] and not _sync_in_progress:
        background_tasks.add_task(_run_dividend_sync_background)
        summary["sync_in_progress"] = True

    return summary


@router.post("/sync")
async def sync_dividends(background_tasks: BackgroundTasks):
    """Manual trigger for dividend sync."""
    if _sync_in_progress:
        return {"status": "already_running", "message": "Dividend sync is already in progress"}
    background_tasks.add_task(_run_dividend_sync_background)
    return {"status": "started", "message": "Dividend sync started in background"}
