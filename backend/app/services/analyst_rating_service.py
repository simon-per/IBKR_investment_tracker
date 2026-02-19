"""
Analyst Rating Service
Fetches analyst recommendations from Yahoo Finance using yfinance library.
Updates ratings twice weekly to avoid excessive API calls.
"""
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import yfinance as yf
import time
import random
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.analyst_rating_repository import AnalystRatingRepository
from app.models.security import Security
from app.models.analyst_rating import AnalystRating


class AnalystRatingService:
    """
    Service for fetching and caching analyst ratings from Yahoo Finance.

    Uses yfinance library to fetch aggregated analyst recommendations
    showing counts of: strong buy, buy, hold, sell, strong sell.

    Caches ratings in database and refreshes twice weekly (every 3-4 days).
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.rating_repo = AnalystRatingRepository(db)

    async def _get_yahoo_ticker(self, security: Security) -> str:
        """
        Convert IBKR security info to Yahoo Finance ticker format.
        Reuses the same logic from market_data_service.
        """
        from app.services.market_data_service import MarketDataService
        market_service = MarketDataService(self.db)
        return await market_service._get_yahoo_ticker(security)

    async def fetch_rating_for_security(self, security: Security) -> Optional[Dict]:
        """
        Fetch analyst rating for a single security from Yahoo Finance.

        Args:
            security: Security object

        Returns:
            Dict with rating counts or None if not available
        """
        try:
            yahoo_ticker = await self._get_yahoo_ticker(security)
            print(f"Fetching analyst rating for {security.symbol} ({yahoo_ticker})...")

            # Add random delay to avoid rate limiting (1-3 seconds)
            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Fetch recommendations using yfinance
            ticker = yf.Ticker(yahoo_ticker)
            recommendations = ticker.recommendations

            if recommendations is None or recommendations.empty:
                print(f"  No analyst ratings available for {security.symbol}")
                return None

            # Get the most recent period (0m = current month)
            latest = recommendations.iloc[0]

            rating_data = {
                'security_id': security.id,
                'strong_buy': int(latest.get('strongBuy', 0)),
                'buy': int(latest.get('buy', 0)),
                'hold': int(latest.get('hold', 0)),
                'sell': int(latest.get('sell', 0)),
                'strong_sell': int(latest.get('strongSell', 0)),
            }

            total = sum([rating_data['strong_buy'], rating_data['buy'],
                        rating_data['hold'], rating_data['sell'],
                        rating_data['strong_sell']])

            print(f"  [OK] Found {total} analyst ratings for {security.symbol}")
            return rating_data

        except Exception as e:
            print(f"  [ERROR] Error fetching rating for {security.symbol}: {str(e)}")
            return None

    async def sync_ratings_for_securities(self, security_ids: Optional[List[int]] = None) -> Dict:
        """
        Sync analyst ratings for specified securities or all securities.

        Args:
            security_ids: List of security IDs to sync. If None, syncs all.

        Returns:
            Dict with sync statistics
        """
        # Get securities
        if security_ids:
            result = await self.db.execute(
                select(Security).where(Security.id.in_(security_ids))
            )
        else:
            result = await self.db.execute(select(Security))

        securities = list(result.scalars().all())

        if not securities:
            return {
                'securities_processed': 0,
                'ratings_updated': 0,
                'errors': 0,
                'message': 'No securities found'
            }

        print(f"\n{'='*60}")
        print(f"Syncing analyst ratings for {len(securities)} securities")
        print(f"{'='*60}\n")

        ratings_updated = 0
        errors = 0

        for i, security in enumerate(securities, 1):
            print(f"\n[{i}/{len(securities)}] Processing {security.symbol} ({security.description[:50]}...)")

            try:
                rating_data = await self.fetch_rating_for_security(security)

                if rating_data:
                    # Save to database
                    await self.rating_repo.upsert(rating_data)
                    ratings_updated += 1
                    await self.db.commit()
                else:
                    print(f"  [WARN] Skipping {security.symbol} - no ratings available")

                # Add delay between securities to avoid rate limiting (2-4 seconds)
                if i < len(securities):
                    delay = random.uniform(2.0, 4.0)
                    print(f"  Waiting {delay:.1f}s before next security...")
                    await asyncio.sleep(delay)

            except Exception as e:
                print(f"  [ERROR] Error processing {security.symbol}: {str(e)}")
                errors += 1
                await self.db.rollback()
                continue

        print(f"\n{'='*60}")
        print(f"Analyst Rating Sync Complete")
        print(f"  Securities Processed: {len(securities)}")
        print(f"  Ratings Updated: {ratings_updated}")
        print(f"  Errors: {errors}")
        print(f"{'='*60}\n")

        return {
            'securities_processed': len(securities),
            'ratings_updated': ratings_updated,
            'errors': errors,
            'message': f'Successfully synced {ratings_updated}/{len(securities)} analyst ratings'
        }

    async def get_stale_ratings(self, days_old: int = 3) -> List[AnalystRating]:
        """
        Get ratings that need to be refreshed (older than specified days).
        Default is 3 days for twice-weekly updates.
        """
        return await self.rating_repo.get_stale_ratings(days_old)

    async def sync_stale_ratings(self) -> Dict:
        """
        Sync only ratings that are stale (haven't been updated in 3+ days).
        This is used for the automated twice-weekly sync.
        """
        stale_ratings = await self.get_stale_ratings(days_old=3)

        if not stale_ratings:
            return {
                'securities_processed': 0,
                'ratings_updated': 0,
                'errors': 0,
                'message': 'No stale ratings to update'
            }

        security_ids = [rating.security_id for rating in stale_ratings]
        print(f"Found {len(security_ids)} stale ratings to refresh")

        return await self.sync_ratings_for_securities(security_ids)

    async def get_rating_for_security(self, security_id: int) -> Optional[AnalystRating]:
        """Get cached analyst rating for a security"""
        return await self.rating_repo.get_by_security_id(security_id)

    async def get_all_ratings(self) -> List[AnalystRating]:
        """Get all cached analyst ratings"""
        return await self.rating_repo.get_all()
