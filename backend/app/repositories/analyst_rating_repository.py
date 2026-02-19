"""
AnalystRating Repository
Handles database operations for analyst ratings.
"""
from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analyst_rating import AnalystRating


class AnalystRatingRepository:
    """Repository for AnalystRating model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_security_id(self, security_id: int) -> Optional[AnalystRating]:
        """Get analyst rating for a specific security"""
        result = await self.session.execute(
            select(AnalystRating).where(AnalystRating.security_id == security_id)
        )
        return result.scalar_one_or_none()

    async def get_all(self) -> List[AnalystRating]:
        """Get all analyst ratings"""
        result = await self.session.execute(select(AnalystRating))
        return list(result.scalars().all())

    async def get_all_with_securities(self) -> List[AnalystRating]:
        """Get all analyst ratings with their security relationships loaded"""
        result = await self.session.execute(
            select(AnalystRating).options(
                # Can add joinedload here if needed for eager loading
            )
        )
        return list(result.scalars().all())

    async def create(self, rating_data: dict) -> AnalystRating:
        """Create a new analyst rating record"""
        rating = AnalystRating(**rating_data)
        self.session.add(rating)
        await self.session.flush()
        await self.session.refresh(rating)
        return rating

    async def upsert(self, rating_data: dict) -> AnalystRating:
        """
        Insert or update analyst rating.
        Uses security_id as unique key (one rating per security).
        """
        existing = await self.get_by_security_id(rating_data['security_id'])

        if existing:
            # Update existing
            for key, value in rating_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            # Always update last_updated timestamp
            existing.last_updated = datetime.now()
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            # Create new
            rating_data['last_updated'] = datetime.now()
            return await self.create(rating_data)

    async def bulk_upsert(self, ratings_data: List[dict]) -> int:
        """
        Bulk insert/update analyst ratings.
        Returns count of records created or updated.
        """
        count = 0
        for rating_data in ratings_data:
            await self.upsert(rating_data)
            count += 1
        return count

    async def delete_by_security_id(self, security_id: int) -> bool:
        """Delete analyst rating for a security"""
        rating = await self.get_by_security_id(security_id)
        if rating:
            await self.session.delete(rating)
            await self.session.flush()
            return True
        return False

    async def get_stale_ratings(self, days_old: int = 3) -> List[AnalystRating]:
        """
        Get ratings that haven't been updated in the specified number of days.
        Useful for determining which ratings need to be refreshed.
        """
        cutoff_date = datetime.now() - timedelta(days=days_old)
        result = await self.session.execute(
            select(AnalystRating).where(AnalystRating.last_updated < cutoff_date)
        )
        return list(result.scalars().all())
