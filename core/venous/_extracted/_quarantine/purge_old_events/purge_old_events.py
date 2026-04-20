from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession


async def purge_old_events(session: AsyncSession, retention_days: int) -> int:
    """Hard-delete compliance events older than retention_days.

    Args:
        session: Async database session.
        retention_days: Records older than this many days are deleted.

    Returns:
        Number of rows deleted.
    """
    from datetime import timedelta
    from sqlalchemy import delete
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    stmt = delete(ComplianceEvent).where(ComplianceEvent.created_at < cutoff)
    result = await session.execute(stmt)
    await session.commit()
    return result.rowcount
