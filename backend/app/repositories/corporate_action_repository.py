from typing import List, Optional
from datetime import date
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_action import CorporateAction


class CorporateActionRepository:
    """Repository for CorporateAction model operations (idempotent on ib_key)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert(self, data: dict) -> CorporateAction:
        result = await self.session.execute(
            select(CorporateAction).where(CorporateAction.ib_key == data["ib_key"])
        )
        existing = result.scalar_one_or_none()

        if existing:
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            await self.session.flush()
            return existing

        action = CorporateAction(**data)
        self.session.add(action)
        await self.session.flush()
        return action

    async def get_by_conid_in_range(
        self, conid: str, start: Optional[date], end: date
    ) -> List[CorporateAction]:
        """Corporate actions for a conid with action_date in (start, end]."""
        stmt = select(CorporateAction).where(
            and_(CorporateAction.conid == str(conid), CorporateAction.action_date <= end)
        )
        if start is not None:
            stmt = stmt.where(CorporateAction.action_date > start)
        stmt = stmt.order_by(CorporateAction.action_date.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(CorporateAction.id)))
        return int(result.scalar() or 0)
