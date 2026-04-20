from __future__ import annotations
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_events_in_range(session: AsyncSession, start: datetime, end: datetime, limit: int=500) -> list[ComplianceEvent]:
    """Return compliance events within a UTC date range.

    Args:
        session: Async database session.
        start: Range start (UTC-aware datetime).
        end: Range end (UTC-aware datetime).
        limit: Maximum rows to return.

    Returns:
        List of ComplianceEvent records in chronological order.
    """
    stmt = select(ComplianceEvent).where(ComplianceEvent.created_at >= start, ComplianceEvent.created_at <= end).order_by(ComplianceEvent.created_at.asc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
