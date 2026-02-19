"""
API endpoints for portfolio allocation data (sector, geography, asset type).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.allocation_service import AllocationService


router = APIRouter()


@router.post("/sync")
async def sync_allocation_data(
    force_refresh: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Sync allocation data for all securities.
    Fetches sector and country information from yfinance with rate limiting.
    Uses cached data unless force_refresh=True or data is >7 days old.
    """
    service = AllocationService(db)
    result = await service.sync_allocation_data(force_refresh=force_refresh)
    return result


@router.get("/portfolio")
async def get_portfolio_allocation(db: AsyncSession = Depends(get_db)):
    """
    Get portfolio allocation breakdown by sector, geography, and asset type.
    Returns weighted percentages based on current market values.
    """
    service = AllocationService(db)
    allocation = await service.get_portfolio_allocation()
    return allocation


@router.get("/status")
async def get_allocation_status(db: AsyncSession = Depends(get_db)):
    """
    Get status of allocation data (how many securities have data, staleness, etc.)
    """
    from sqlalchemy import select, func
    from app.models.security import Security
    from datetime import datetime, timedelta

    # Count securities with/without allocation data
    result = await db.execute(select(func.count(Security.id)))
    total_securities = result.scalar()

    result = await db.execute(
        select(func.count(Security.id)).where(Security.allocation_last_updated.isnot(None))
    )
    securities_with_data = result.scalar()

    # Count stale data (>7 days old)
    cutoff_date = datetime.now() - timedelta(days=7)
    result = await db.execute(
        select(func.count(Security.id)).where(
            Security.allocation_last_updated < cutoff_date
        )
    )
    stale_securities = result.scalar()

    # Get oldest and newest update times
    result = await db.execute(
        select(func.min(Security.allocation_last_updated))
        .where(Security.allocation_last_updated.isnot(None))
    )
    oldest_update = result.scalar()

    result = await db.execute(
        select(func.max(Security.allocation_last_updated))
        .where(Security.allocation_last_updated.isnot(None))
    )
    newest_update = result.scalar()

    return {
        'total_securities': total_securities or 0,
        'securities_with_data': securities_with_data or 0,
        'securities_without_data': (total_securities or 0) - (securities_with_data or 0),
        'stale_securities': stale_securities or 0,
        'oldest_update': oldest_update.isoformat() if oldest_update else None,
        'newest_update': newest_update.isoformat() if newest_update else None,
    }
