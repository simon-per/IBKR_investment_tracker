"""
Market Data Router
API endpoints for syncing and managing market price data.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.market_data_service import MarketDataService
from app.repositories.security_repository import SecurityRepository
from app.single_flight import SYNC_PIPELINE, SyncBusy, single_flight

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/sync")
async def sync_market_data(
    # Bounded: this drives a no-await per-day Python loop per security, so an
    # unbounded value from the public internet would block the event loop.
    days_back: int = Query(730, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
):
    """
    Sync historical market prices for all securities.

    Args:
        days_back: Number of days to look back (default 730 = 2 years)

    This endpoint:
    1. Fetches all securities from the database
    2. For each security, fetches missing historical prices
    3. Caches prices in the database

    Uses Yahoo Finance as the primary data source with exchange-specific tickers.

    Returns:
        Summary of synced data including counts and any errors
    """
    try:
        # Shared pipeline gate: a full market sync is 50-150+ Yahoo requests, and
        # racing the scheduled jobs doubles that against an IP-based rate limit.
        with single_flight(SYNC_PIPELINE, cooldown_seconds=300):
            return await _sync_market_data_locked(days_back, db)
    except SyncBusy as e:
        raise HTTPException(
            status_code=429, detail=str(e),
            headers={"Retry-After": str(e.retry_after_seconds)},
        )
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync market data: {str(e)}"
        )


async def _sync_market_data_locked(days_back: int, db: AsyncSession):
    """The sync body, run while holding the pipeline gate."""
    market_data_service = MarketDataService(db)
    security_repo = SecurityRepository(db)

    # Get all securities
    securities = await security_repo.get_all(limit=1000)

    if not securities:
        return {
            "status": "success",
            "message": "No securities found to sync",
            "securities_processed": 0,
            "prices_fetched": 0
        }

    # Shared with SchedulerService.sync_market_data rather than reimplemented here.
    # This route used to carry its own copy of the loop, which is how it ended up
    # without the Yahoo rate-limit breaker the scheduled job gained — a public,
    # reachable path that kept asking after being told to back off. The extra
    # inter-security sleep this copy had is dropped with it: `fetch_and_cache_prices`
    # already paces 3-6s per security, so it was double-pacing the one path nobody
    # was measuring.
    swept = await market_data_service.sync_securities(securities, days_back=days_back)
    errors = swept["errors"]
    rate_limited_after = swept["rate_limited_after"]

    # Commit all price data
    await db.commit()

    result = {
        "status": "success" if not (errors or rate_limited_after) else "partial_success",
        "message": (
            f"Synced market data for {swept['processed']} of {len(securities)} securities"
        ),
        "securities_processed": swept["processed"],
        "prices_fetched": swept["total_prices"],
    }

    if errors:
        result["errors"] = errors
        result["errors_count"] = len(errors)

    if rate_limited_after:
        result["rate_limited"] = True
        result["warnings"] = [
            f"Yahoo rate-limited this run at {rate_limited_after}; "
            f"{len(securities) - swept['processed']} securities were skipped and keep "
            f"their previous prices. Do not retry — wait for the next scheduled slot"
        ]

    return result


@router.get("/status")
async def get_market_data_status(db: AsyncSession = Depends(get_db)):
    """
    Get status of market data cache.

    Returns:
        Statistics about cached market prices
    """
    from app.repositories.market_price_repository import MarketPriceRepository

    price_repo = MarketPriceRepository(db)

    # Get total count and date range
    from sqlalchemy import select, func
    from app.models.market_price import MarketPrice

    result = await db.execute(
        select(
            func.count(MarketPrice.id),
            func.min(MarketPrice.date),
            func.max(MarketPrice.date)
        )
    )
    count, min_date, max_date = result.one()

    return {
        "total_prices": count,
        "earliest_date": str(min_date) if min_date else None,
        "latest_date": str(max_date) if max_date else None,
    }
