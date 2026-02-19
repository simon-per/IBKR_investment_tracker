"""
Security Repository
Handles database operations for Securities.
"""
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert

from app.models.security import Security


class SecurityRepository:
    """Repository for Security model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, security_id: int) -> Optional[Security]:
        """Get security by ID"""
        result = await self.session.execute(
            select(Security).where(Security.id == security_id)
        )
        return result.scalar_one_or_none()

    async def get_by_conid(self, conid: int) -> Optional[Security]:
        """Get security by IBKR conid (unique identifier)"""
        result = await self.session.execute(
            select(Security).where(Security.conid == conid)
        )
        return result.scalar_one_or_none()

    async def get_by_isin_exchange(self, isin: str, exchange: Optional[str]) -> Optional[Security]:
        """Get security by ISIN and exchange (composite unique key)"""
        query = select(Security).where(Security.isin == isin)
        if exchange:
            query = query.where(Security.exchange == exchange)
        else:
            query = query.where(Security.exchange.is_(None))

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[Security]:
        """Get all securities with pagination"""
        result = await self.session.execute(
            select(Security).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, security_data: dict) -> Security:
        """Create a new security"""
        security = Security(**security_data)
        self.session.add(security)
        await self.session.flush()
        await self.session.refresh(security)
        return security

    async def upsert(self, security_data: dict) -> Security:
        """
        Insert or update security.
        Uses conid as the unique identifier for upsert.
        """
        # Try to find existing by conid
        existing = await self.get_by_conid(security_data['conid'])

        if existing:
            # Update existing
            for key, value in security_data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            # Create new
            return await self.create(security_data)

    async def bulk_upsert(self, securities_data: List[dict]) -> int:
        """
        Bulk upsert securities.
        Returns count of affected rows.

        Note: For SQLite, we use a simpler approach of individual upserts
        since SQLite's upsert syntax is different from PostgreSQL.
        """
        count = 0
        for security_data in securities_data:
            await self.upsert(security_data)
            count += 1
        return count

    async def delete(self, security_id: int) -> bool:
        """Delete a security by ID"""
        security = await self.get_by_id(security_id)
        if security:
            await self.session.delete(security)
            await self.session.flush()
            return True
        return False
