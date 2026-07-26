import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sync_run import SyncRun

logger = logging.getLogger(__name__)


def utc_iso(value: Optional[datetime]) -> Optional[str]:
    """
    Serialize a timestamp so a browser can't misread it.

    The container runs on UTC and these columns hold naive UTC datetimes, so a bare
    `isoformat()` emits "2026-07-26T06:02:46" — which `new Date(...)` in the browser
    parses as *local* time. The dashboard therefore showed the 08:00 Europe/Berlin sync
    as having run at 06:02, right beside a "Next: 13:00" that APScheduler had correctly
    tagged "+02:00". Two clocks on one line, and a real failure looked like a different,
    later one. Stamping UTC explicitly makes the browser convert instead of guess.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class SyncRunRepository:
    """Repository for the persisted sync history."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def record(
        self,
        sync_type: str,
        status: str,
        message: Optional[str] = None,
        details: Optional[Any] = None,
        warnings: Optional[Any] = None,
        started_at: Optional[datetime] = None,
    ) -> Optional[SyncRun]:
        """
        Persist one sync attempt, committing on its own.

        Deliberately swallows its own failures: this is bookkeeping, and a broken
        insert must never turn a successful sync into a failure, nor replace the real
        exception on the error path. Returns None if it couldn't record.
        """
        try:
            run = SyncRun(
                sync_type=sync_type,
                status=status,
                message=(message or "")[:2000] or None,
                details=details,
                warnings=warnings or None,
                started_at=started_at,
                finished_at=datetime.now(),
            )
            self.session.add(run)
            await self.session.commit()
            return run
        except Exception as e:
            logger.warning(f"Could not record sync run ({sync_type}/{status}): {e}")
            try:
                await self.session.rollback()
            except Exception:
                pass
            return None

    async def get_latest(self, sync_type: Optional[str] = None) -> Optional[SyncRun]:
        stmt = select(SyncRun).order_by(SyncRun.finished_at.desc(), SyncRun.id.desc()).limit(1)
        if sync_type:
            stmt = stmt.where(SyncRun.sync_type == sync_type)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_recent(self, limit: int = 20) -> List[SyncRun]:
        result = await self.session.execute(
            select(SyncRun)
            .order_by(SyncRun.finished_at.desc(), SyncRun.id.desc())
            .limit(max(1, min(limit, 200)))
        )
        return list(result.scalars().all())

    @staticmethod
    def to_dict(run: SyncRun) -> Dict:
        """Shape a run like the in-memory last_sync_result, so consumers see one format."""
        return {
            "type": run.sync_type,
            "status": run.status,
            "message": run.message,
            "timestamp": utc_iso(run.finished_at),
            "details": run.details,
            "warnings": run.warnings,
        }
