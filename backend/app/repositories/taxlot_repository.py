"""
TaxLot Repository
Handles database operations for Tax Lots.
"""
from typing import List, Optional
from datetime import date
from sqlalchemy import select, delete, and_
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

    async def create_many(self, rows: List[dict]) -> int:
        """
        Insert many tax lots with one flush and no per-row refresh.

        ``create()`` flushes *and* refreshes each lot — two round trips per row,
        and reconciliation writes every open lot on every sync (~975 here, so
        ~1,950 statements) while discarding all of the returned objects. Callers
        that need the persisted object back should still use ``create()``.
        """
        if not rows:
            return 0
        self.session.add_all([TaxLot(**row) for row in rows])
        await self.session.flush()
        return len(rows)

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

    async def delete_open_by_security_id(self, security_id: int) -> int:
        """
        Delete only OPEN tax lots for a security, preserving closed (historical) lots.
        Returns count of deleted lots.
        """
        return await self.delete_open_by_security_ids([security_id])

    async def delete_open_by_security_ids(self, security_ids) -> int:
        """
        Delete the OPEN lots of many securities in one statement, preserving closed
        (historical) lots. Returns the count deleted.

        Reconciliation calls this once per sync for every security it touched. It
        used to be a loop of per-security calls, each of which ran a SELECT and then
        an ORM delete per row — an N+1 inside an N+1, ~40 extra round trips on this
        portfolio before a single lot was written.

        ``synchronize_session="fetch"`` matters: the caller is holding the very rows
        this removes (it snapshots them first), and a bulk DELETE goes behind the
        ORM's back. "fetch" costs one extra SELECT and leaves the identity map
        correct, where the alternative is stale objects that reappear on flush.
        """
        ids = list(security_ids)
        if not ids:
            return 0
        result = await self.session.execute(
            delete(TaxLot)
            .where(and_(TaxLot.security_id.in_(ids), TaxLot.is_open == True))  # noqa: E712
            .execution_options(synchronize_session="fetch")
        )
        await self.session.flush()
        return result.rowcount or 0
