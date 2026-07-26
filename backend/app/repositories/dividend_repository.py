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
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        source: Optional[str] = None,
    ) -> List[DividendPayment]:
        stmt = select(DividendPayment).where(
            DividendPayment.gross_amount_eur.isnot(None)
        )
        if source is not None:
            stmt = stmt.where(DividendPayment.source == source)
        if start_date:
            stmt = stmt.where(DividendPayment.ex_date >= start_date)
        if end_date:
            stmt = stmt.where(DividendPayment.ex_date <= end_date)
        stmt = stmt.order_by(DividendPayment.ex_date.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def has_ibkr_dividends(
        self, start: Optional[date] = None, end: Optional[date] = None
    ) -> bool:
        """
        True if authoritative IBKR-sourced dividend rows exist, optionally only within
        [start, end].

        Callers that report per year MUST pass the window. A Flex Query only returns cash
        transactions inside its period, so a year-to-date sync leaves earlier years with
        estimates only — asking globally would make a prior-year report filter to `ibkr`,
        find nothing, and present 0.00 as authoritative.

        The window uses `pay_date` falling back to `ex_date`, matching how TaxService
        buckets a payment into a year, so the flag can never disagree with the rows shown.
        """
        stmt = select(func.count(DividendPayment.id)).where(DividendPayment.source == "ibkr")
        on_date = func.coalesce(DividendPayment.pay_date, DividendPayment.ex_date)
        if start is not None:
            stmt = stmt.where(on_date >= start)
        if end is not None:
            stmt = stmt.where(on_date <= end)
        result = await self.session.execute(stmt)
        return int(result.scalar() or 0) > 0

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
