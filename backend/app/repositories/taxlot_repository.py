"""
TaxLot Repository
Handles database operations for Tax Lots.
"""
from typing import List, Optional
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.taxlot import TaxLot
from app.models.security import Security


class TaxLotRepository:
    """Repository for TaxLot model operations"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, taxlot_id: int) -> Optional[TaxLot]:
        """Get tax lot by ID with related security"""
        result = await self.session.execute(
            select(TaxLot)
            .options(joinedload(TaxLot.security))
            .where(TaxLot.id == taxlot_id)
        )
        return result.scalar_one_or_none()

    async def get_by_security_id(
        self,
        security_id: int,
        is_open: Optional[bool] = None
    ) -> List[TaxLot]:
        """Get all tax lots for a specific security"""
        query = select(TaxLot).where(TaxLot.security_id == security_id)

        if is_open is not None:
            query = query.where(TaxLot.is_open == is_open)

        result = await self.session.execute(query.order_by(TaxLot.open_date))
        return list(result.scalars().all())

    async def get_open_taxlots(self) -> List[TaxLot]:
        """Get all open (active) tax lots with their securities"""
        result = await self.session.execute(
            select(TaxLot)
            .options(joinedload(TaxLot.security))
            .where(TaxLot.is_open == True)
            .order_by(TaxLot.open_date)
        )
        return list(result.scalars().all())

    async def get_taxlots_on_date(self, target_date: date) -> List[TaxLot]:
        """
        Get all tax lots that were active on a specific date.
        A tax lot is active if:
        - open_date <= target_date
        - close_date is None OR close_date > target_date
        """
        result = await self.session.execute(
            select(TaxLot)
            .options(joinedload(TaxLot.security))
            .where(TaxLot.open_date <= target_date)
            .where(
                (TaxLot.close_date.is_(None)) |
                (TaxLot.close_date > target_date)
            )
            .order_by(TaxLot.security_id, TaxLot.open_date)
        )
        return list(result.scalars().all())

    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        is_open: Optional[bool] = None
    ) -> List[TaxLot]:
        """Get all tax lots with pagination and optional filtering"""
        query = select(TaxLot).options(joinedload(TaxLot.security))

        if is_open is not None:
            query = query.where(TaxLot.is_open == is_open)

        result = await self.session.execute(
            query.order_by(TaxLot.open_date.desc()).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, taxlot_data: dict) -> TaxLot:
        """Create a new tax lot"""
        taxlot = TaxLot(**taxlot_data)
        self.session.add(taxlot)
        await self.session.flush()
        await self.session.refresh(taxlot)
        return taxlot

    async def update(self, taxlot_id: int, taxlot_data: dict) -> Optional[TaxLot]:
        """Update an existing tax lot"""
        taxlot = await self.get_by_id(taxlot_id)
        if taxlot:
            for key, value in taxlot_data.items():
                if hasattr(taxlot, key):
                    setattr(taxlot, key, value)
            await self.session.flush()
            await self.session.refresh(taxlot)
        return taxlot

    async def close_taxlot(self, taxlot_id: int, close_date: date) -> Optional[TaxLot]:
        """Mark a tax lot as closed"""
        return await self.update(taxlot_id, {
            'is_open': False,
            'close_date': close_date
        })

    async def delete(self, taxlot_id: int) -> bool:
        """Delete a tax lot by ID"""
        taxlot = await self.get_by_id(taxlot_id)
        if taxlot:
            await self.session.delete(taxlot)
            await self.session.flush()
            return True
        return False

    async def delete_by_security_id(self, security_id: int) -> int:
        """
        Delete all tax lots for a security.
        Returns count of deleted lots.
        """
        taxlots = await self.get_by_security_id(security_id)
        count = len(taxlots)
        for taxlot in taxlots:
            await self.session.delete(taxlot)
        await self.session.flush()
        return count
