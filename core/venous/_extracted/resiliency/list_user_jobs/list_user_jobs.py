from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def list_user_jobs(session: AsyncSession, *, user_id: uuid.UUID, limit: int=50) -> list[Job]:
    """Return the most recent jobs triggered by *user_id*.

    Args:
        session: Async database session.
        user_id: UUID of the user who triggered the jobs.
        limit: Maximum number of rows to return (default 50).

    Returns:
        List of ``Job`` instances, newest first.
    """
    stmt = select(Job).where(Job.user_id == user_id).order_by(Job.enqueued_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())
