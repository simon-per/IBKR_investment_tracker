"""
Market Data Router
API endpoints for syncing and managing market price data.
"""
import asyncio
import random
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.market_data_service import MarketDataService
from app.repositories.security_repository import SecurityRepository


router = APIRouter()


@router.post("/sync")
async def sync_market_data(days_back: int = 730, db: AsyncSession = Depends(get_db)):
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

        total_prices = 0
        errors = []

        print(f"\n=== SYNCING MARKET DATA FOR {len(securities)} SECURITIES ===")

        for idx, security in enumerate(securities):
            try:
                print(f"Fetching prices for {security.symbol} ({security.exchange})...")

                # Fetch historical data
                prices_count = await market_data_service.sync_security_prices(
                    security,
                    days_back=days_back
                )

                total_prices += prices_count
                print(f"  [OK] Fetched {prices_count} price points")

                # Add delay between securities to avoid overwhelming Yahoo Finance
                # Skip delay after the last security
                if idx < len(securities) - 1:
                    delay = random.uniform(2.0, 4.0)
                    print(f"  [WAIT] Waiting {delay:.1f}s before next security...")
                    await asyncio.sleep(delay)

            except Exception as e:
                error_msg = f"Failed to fetch prices for {security.symbol}: {str(e)}"
                print(f"  [ERROR] {error_msg}")
                errors.append(error_msg)

        # Commit all price data
        await db.commit()

        result = {
            "status": "success" if not errors else "partial_success",
            "message": f"Synced market data for {len(securities)} securities",
            "securities_processed": len(securities),
            "prices_fetched": total_prices,
        }

        if errors:
            result["errors"] = errors
            result["errors_count"] = len(errors)

        return result

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync market data: {str(e)}"
        )


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
