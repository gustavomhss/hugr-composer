from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def update_job_failed(session: AsyncSession, *, job_id: uuid.UUID, error: str) -> Job | None:
    """Mark *job_id* as ``failed`` and persist *error*.

    Args:
        session: Async database session.
        job_id: UUID primary key of the job row.
        error: Human-readable failure message (truncated to 4k chars).

    Returns:
        The updated ``Job`` or ``None`` if not found.
    """
    job = await _get(session, job_id)
    if job is None:
        return None
    job.status = 'failed'
    job.error = error[:4000]
    job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job
