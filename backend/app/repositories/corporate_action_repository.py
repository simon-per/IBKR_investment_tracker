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

    async def existing_ib_keys(self, ib_keys: List[str]) -> set:
        """
        Which of these ``ib_key``s are already stored.

        Lets a caller tell an insert from an update across a batch of ``upsert()``
        calls in one query. That distinction is what makes the split-driven price-cache
        purge idempotent: without it, every sync would re-purge the same split and
        trigger a re-fetch of the whole history behind it.
        """
        keys = [k for k in ib_keys if k]
        if not keys:
            return set()
        result = await self.session.execute(
            select(CorporateAction.ib_key).where(CorporateAction.ib_key.in_(keys))
        )
        return {row[0] for row in result.all()}

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

    async def get_between(self, start: date, end: date) -> List[CorporateAction]:
        """
        All actions with action_date in [start, end], oldest first.

        Inclusive at both ends, unlike ``get_by_conid_in_range`` above, which is
        deliberately half-open because reconciliation walks forward from a lot's last
        known state. This one answers "what happened in this window", where excluding
        the first day would drop an action the caller explicitly asked about.
        """
        result = await self.session.execute(
            select(CorporateAction)
            .where(and_(CorporateAction.action_date >= start,
                        CorporateAction.action_date <= end))
            .order_by(CorporateAction.action_date.asc())
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(select(func.count(CorporateAction.id)))
        return int(result.scalar() or 0)
