from typing import List, Optional
from datetime import date
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cash_flow import CashFlow, DEPOSIT_WITHDRAW, TRANSFER_IN


class CashFlowRepository:
    """Repository for CashFlow model operations (idempotent on ib_key)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, data: dict) -> CashFlow:
        result = await self.session.execute(
            select(CashFlow).where(CashFlow.ib_key == data["ib_key"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            return existing

        flow = CashFlow(**data)
        self.session.add(flow)
        await self.session.flush()
        return flow

    async def get_all(self) -> List[CashFlow]:
        result = await self.session.execute(
            select(CashFlow).order_by(CashFlow.flow_date.asc())
        )
        return list(result.scalars().all())

    async def get_deposits(self) -> List[CashFlow]:
        """
        Deposits and withdrawals only — real external money.

        TRANSFER rows are deliberately excluded: an incoming transfer moves capital
        that was already saved at another broker, and the transferred lots already
        carry their original open_date, so counting it here would both invent a
        contribution and double-count the original purchase.
        """
        result = await self.session.execute(
            select(CashFlow)
            .where(CashFlow.flow_type == DEPOSIT_WITHDRAW)
            .order_by(CashFlow.flow_date.asc())
        )
        return list(result.scalars().all())

    async def get_between(self, start: date, end: date) -> List[CashFlow]:
        """All flows with flow_date in [start, end]."""
        result = await self.session.execute(
            select(CashFlow)
            .where(and_(CashFlow.flow_date >= start, CashFlow.flow_date <= end))
            .order_by(CashFlow.flow_date.asc())
        )
        return list(result.scalars().all())

    async def earliest_deposit_date(self) -> Optional[date]:
        """
        Date of the oldest deposit/withdrawal, or None if there are none.

        This is the coverage floor for the contributions report. The Flex Query is
        Year to Date and the earlier history arrived by broker transfer, so there is
        simply no deposit data before this date — a window reaching further back has
        to say so rather than average over months it cannot see. Transfers are
        excluded so an incoming one can't backdate the floor past real coverage.
        """
        result = await self.session.execute(
            select(func.min(CashFlow.flow_date)).where(CashFlow.flow_type == DEPOSIT_WITHDRAW)
        )
        return result.scalar()

    async def earliest_transfer_in_date(self) -> Optional[date]:
        """Date of the oldest incoming transfer — informational, to explain the floor."""
        result = await self.session.execute(
            select(func.min(CashFlow.flow_date)).where(CashFlow.flow_type == TRANSFER_IN)
        )
        return result.scalar()

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(CashFlow.id)))
        return int(result.scalar() or 0)
