from typing import List, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fundamental_metrics import FundamentalMetrics
from app.models.earnings_event import EarningsEvent


class FundamentalsRepository:
    """Repository for FundamentalMetrics and EarningsEvent model operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # --- FundamentalMetrics ---

    async def get_metrics_by_security_id(self, security_id: int) -> Optional[FundamentalMetrics]:
        result = await self.session.execute(
            select(FundamentalMetrics).where(FundamentalMetrics.security_id == security_id)
        )
        return result.scalar_one_or_none()

    async def get_all_metrics(self) -> List[FundamentalMetrics]:
        result = await self.session.execute(select(FundamentalMetrics))
        return list(result.scalars().all())

    async def get_stale_metrics(self, days_old: int = 7) -> List[FundamentalMetrics]:
        cutoff_date = datetime.now() - timedelta(days=days_old)
        result = await self.session.execute(
            select(FundamentalMetrics).where(FundamentalMetrics.last_updated < cutoff_date)
        )
        return list(result.scalars().all())

    async def upsert_metrics(self, data: dict) -> FundamentalMetrics:
        existing = await self.get_metrics_by_security_id(data['security_id'])

        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            existing.last_updated = datetime.now()
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            data['last_updated'] = datetime.now()
            metrics = FundamentalMetrics(**data)
            self.session.add(metrics)
            await self.session.flush()
            await self.session.refresh(metrics)
            return metrics

    # --- EarningsEvent ---

    async def get_earnings_by_security(self, security_id: int) -> List[EarningsEvent]:
        result = await self.session.execute(
            select(EarningsEvent)
            .where(EarningsEvent.security_id == security_id)
            .order_by(EarningsEvent.earnings_date.desc())
        )
        return list(result.scalars().all())

    async def upsert_earnings_event(self, data: dict) -> EarningsEvent:
        result = await self.session.execute(
            select(EarningsEvent).where(
                and_(
                    EarningsEvent.security_id == data['security_id'],
                    EarningsEvent.earnings_date == data['earnings_date'],
                )
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            await self.session.refresh(existing)
            return existing
        else:
            event = EarningsEvent(**data)
            self.session.add(event)
            await self.session.flush()
            await self.session.refresh(event)
            return event

    async def get_upcoming_earnings(self, days_ahead: int = 90) -> List[EarningsEvent]:
        now = datetime.now()
        cutoff = now + timedelta(days=days_ahead)
        result = await self.session.execute(
            select(EarningsEvent)
            .options(joinedload(EarningsEvent.security))
            .where(
                and_(
                    EarningsEvent.earnings_date >= now,
                    EarningsEvent.earnings_date <= cutoff,
                )
            )
            .order_by(EarningsEvent.earnings_date.asc())
        )
        return list(result.unique().scalars().all())

    async def get_recent_earnings(self, days_back: int = 365) -> List[EarningsEvent]:
        now = datetime.now()
        cutoff = now - timedelta(days=days_back)
        result = await self.session.execute(
            select(EarningsEvent)
            .options(joinedload(EarningsEvent.security))
            .where(
                and_(
                    EarningsEvent.earnings_date < now,
                    EarningsEvent.earnings_date >= cutoff,
                    EarningsEvent.reported_eps.isnot(None),
                )
            )
            .order_by(EarningsEvent.earnings_date.desc())
        )
        return list(result.unique().scalars().all())
