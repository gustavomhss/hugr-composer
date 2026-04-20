from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import uuid


async def update_job_completed(session: AsyncSession, *, job_id: uuid.UUID, result: dict[str, Any]) -> Job | None:
    """Mark *job_id* as ``success`` and persist *result*.

    Args:
        session: Async database session.
        job_id: UUID primary key of the job row.
        result: JSON-serialisable task return value.

    Returns:
        The updated ``Job`` or ``None`` if not found.
    """
    job = await _get(session, job_id)
    if job is None:
        return None
    job.status = 'success'
    job.result = result
    job.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return job
