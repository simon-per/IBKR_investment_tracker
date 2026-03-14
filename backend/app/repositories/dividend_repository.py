from typing import List, Optional
from datetime import date, datetime
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dividend_payment import DividendPayment


class DividendRepository:
    """Repository for DividendPayment model operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_security(self, security_id: int) -> List[DividendPayment]:
        result = await self.session.execute(
            select(DividendPayment)
            .where(DividendPayment.security_id == security_id)
            .order_by(DividendPayment.ex_date.desc())
        )
        return list(result.scalars().all())

    async def get_latest_ex_date(self, security_id: int) -> Optional[date]:
        result = await self.session.execute(
            select(func.max(DividendPayment.ex_date))
            .where(DividendPayment.security_id == security_id)
        )
        return result.scalar_one_or_none()

    async def upsert_payment(self, data: dict) -> DividendPayment:
        result = await self.session.execute(
            select(DividendPayment).where(
                and_(
                    DividendPayment.security_id == data['security_id'],
                    DividendPayment.ex_date == data['ex_date'],
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            return existing
        else:
            payment = DividendPayment(**data)
            self.session.add(payment)
            await self.session.flush()
            return payment

    async def get_computed_dividends(
        self, start_date: Optional[date] = None, end_date: Optional[date] = None
    ) -> List[DividendPayment]:
        stmt = select(DividendPayment).where(
            DividendPayment.gross_amount_eur.isnot(None)
        )
        if start_date:
            stmt = stmt.where(DividendPayment.ex_date >= start_date)
        if end_date:
            stmt = stmt.where(DividendPayment.ex_date <= end_date)
        stmt = stmt.order_by(DividendPayment.ex_date.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_uncomputed(self) -> List[DividendPayment]:
        result = await self.session.execute(
            select(DividendPayment).where(
                DividendPayment.shares_held.is_(None)
            ).order_by(DividendPayment.ex_date.asc())
        )
        return list(result.scalars().all())

    async def get_last_fetch_time(self, security_id: int) -> Optional[datetime]:
        result = await self.session.execute(
            select(func.max(DividendPayment.created_at))
            .where(DividendPayment.security_id == security_id)
        )
        return result.scalar_one_or_none()
