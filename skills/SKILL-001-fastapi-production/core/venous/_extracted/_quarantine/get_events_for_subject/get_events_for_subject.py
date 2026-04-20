from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def get_events_for_subject(session: AsyncSession, subject_id: str, limit: int=100) -> list[ComplianceEvent]:
    """Return compliance events related to a specific data subject.

    Args:
        session: Async database session.
        subject_id: The data subject's ID.
        limit: Maximum number of rows to return.

    Returns:
        List of ComplianceEvent records, newest first.
    """
    stmt = select(ComplianceEvent).where(ComplianceEvent.subject_id == subject_id).order_by(ComplianceEvent.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
