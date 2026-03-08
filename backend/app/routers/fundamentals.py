from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.fundamentals_service import FundamentalsService

router = APIRouter()


@router.post("/sync")
async def sync_fundamentals(
    force_refresh: bool = Query(False, description="Force refresh all, even fresh data"),
    db: AsyncSession = Depends(get_db),
):
    """Sync fundamental metrics and earnings for all securities."""
    try:
        service = FundamentalsService(db)
        result = await service.sync_fundamentals_data(force_refresh=force_refresh)

        if result['errors'] > 0:
            return {"status": "partial_success", **result}

        return {"status": "success", **result}

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to sync fundamentals: {str(e)}")


@router.post("/sync-stale")
async def sync_stale_fundamentals(db: AsyncSession = Depends(get_db)):
    """Sync only fundamentals that are stale (older than 7 days)."""
    try:
        service = FundamentalsService(db)
        result = await service.sync_stale_fundamentals()
        return {"status": "success", **result}

    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to sync stale fundamentals: {str(e)}")


@router.get("/portfolio")
async def get_portfolio_fundamentals(db: AsyncSession = Depends(get_db)):
    """Get fundamental metrics for all portfolio securities."""
    service = FundamentalsService(db)
    return await service.get_fundamentals_for_portfolio()


@router.get("/earnings/upcoming")
async def get_upcoming_earnings(
    days_ahead: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Get upcoming earnings dates for portfolio securities."""
    service = FundamentalsService(db)
    return await service.get_earnings_calendar(days_ahead)


@router.get("/earnings/history")
async def get_earnings_history(
    days_back: int = Query(365, ge=1, le=1825),
    db: AsyncSession = Depends(get_db),
):
    """Get past earnings with surprise data for portfolio securities."""
    service = FundamentalsService(db)
    return await service.get_earnings_history(days_back)


@router.get("/status")
async def get_fundamentals_status(db: AsyncSession = Depends(get_db)):
    """Get status of fundamentals data cache."""
    from sqlalchemy import select, func
    from app.models.fundamental_metrics import FundamentalMetrics
    from app.models.earnings_event import EarningsEvent
    from app.models.security import Security
    from datetime import datetime, timedelta

    # Count total securities
    total_result = await db.execute(select(func.count(Security.id)))
    total_securities = total_result.scalar() or 0

    # Count metrics
    metrics_result = await db.execute(select(func.count(FundamentalMetrics.id)))
    total_metrics = metrics_result.scalar() or 0

    # Count stale metrics
    seven_days_ago = datetime.now() - timedelta(days=7)
    stale_result = await db.execute(
        select(func.count(FundamentalMetrics.id))
        .where(FundamentalMetrics.last_updated < seven_days_ago)
    )
    stale_metrics = stale_result.scalar() or 0

    # Count earnings events
    earnings_result = await db.execute(select(func.count(EarningsEvent.id)))
    total_earnings = earnings_result.scalar() or 0

    # Update timestamps
    update_result = await db.execute(
        select(
            func.min(FundamentalMetrics.last_updated),
            func.max(FundamentalMetrics.last_updated),
        )
    )
    oldest_update, newest_update = update_result.one()

    return {
        "total_securities": total_securities,
        "securities_with_data": total_metrics,
        "securities_without_data": total_securities - total_metrics,
        "stale_metrics": stale_metrics,
        "total_earnings_events": total_earnings,
        "oldest_update": str(oldest_update) if oldest_update else None,
        "newest_update": str(newest_update) if newest_update else None,
    }
