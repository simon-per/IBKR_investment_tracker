"""
MarketPrice Repository
Handles database operations for historical market prices.
"""
from typing import List, Optional
from datetime import date, timedelta
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from decimal import Decimal

from app.models.market_price import MarketPrice


class MarketPriceRepository:
    """Repository for MarketPrice model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_security_and_date(
        self, security_id: int, target_date: date
    ) -> Optional[MarketPrice]:
        """Get market price for a specific security and date"""
        result = await self.session.execute(
            select(MarketPrice).where(
                and_(
                    MarketPrice.security_id == security_id,
                    MarketPrice.date == target_date
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_price(self, security_id: int) -> Optional[MarketPrice]:
        """Get the most recent market price for a security"""
        result = await self.session.execute(
            select(MarketPrice)
            .where(MarketPrice.security_id == security_id)
            .order_by(MarketPrice.date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_price_range(
        self, security_id: int, start_date: date, end_date: date
    ) -> List[MarketPrice]:
        """Get all prices for a security within a date range"""
        result = await self.session.execute(
            select(MarketPrice)
            .where(
                and_(
                    MarketPrice.security_id == security_id,
                    MarketPrice.date >= start_date,
                    MarketPrice.date <= end_date
                )
            )
            .order_by(MarketPrice.date.asc())
        )
        return list(result.scalars().all())

    async def get_missing_dates(
        self, security_id: int, start_date: date, end_date: date
    ) -> List[date]:
        """
        Find dates in range that don't have cached prices.
        Returns a list of dates that need to be fetched from API.
        """
        # Get all existing dates in the range
        result = await self.session.execute(
            select(MarketPrice.date)
            .where(
                and_(
                    MarketPrice.security_id == security_id,
                    MarketPrice.date >= start_date,
                    MarketPrice.date <= end_date
                )
            )
        )
        existing_dates = set(row[0] for row in result.all())

        # Generate all dates in range (excluding weekends for market data)
        missing_dates = []
        current_date = start_date
        while current_date <= end_date:
            # Skip weekends (Saturday=5, Sunday=6)
            if current_date.weekday() < 5 and current_date not in existing_dates:
                missing_dates.append(current_date)
            current_date += timedelta(days=1)

        return missing_dates

    async def create(self, price_data: dict) -> MarketPrice:
        """Create a new market price record"""
        market_price = MarketPrice(**price_data)
        self.session.add(market_price)
        await self.session.flush()
        await self.session.refresh(market_price)
        return market_price

    async def upsert(self, price_data: dict) -> MarketPrice:
        """
        Insert or update market price.
        Uses security_id + date as unique key.
        """
        existing = await self.get_by_security_and_date(
            price_data['security_id'],
            price_data['date']
        )

        if existing:
            # Update existing
            for key, value in price_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            # Create new
            return await self.create(price_data)

    async def bulk_create(self, prices_data: List[dict]) -> int:
        """
        Bulk insert market prices.
        Returns count of records created.
        """
        count = 0
        for price_data in prices_data:
            await self.upsert(price_data)
            count += 1
        return count

    async def get_date_range_for_security(
        self, security_id: int
    ) -> Optional[tuple[date, date]]:
        """Get the earliest and latest dates we have data for a security"""
        result = await self.session.execute(
            select(
                func.min(MarketPrice.date),
                func.max(MarketPrice.date)
            ).where(MarketPrice.security_id == security_id)
        )
        row = result.one()
        if row[0] and row[1]:
            return (row[0], row[1])
        return None

    async def count_by_security(self, security_id: int) -> int:
        """Count how many price records exist for a security"""
        result = await self.session.execute(
            select(func.count(MarketPrice.id))
            .where(MarketPrice.security_id == security_id)
        )
        return result.scalar() or 0
