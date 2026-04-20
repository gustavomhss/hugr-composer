from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import uuid


async def record_job(session: AsyncSession, *, task_name: str, payload: dict[str, Any], user_id: uuid.UUID | None=None) -> Job:
    """Create a new ``queued`` audit row for a job about to be enqueued.

    Args:
        session: Async database session.
        task_name: Registered task function name.
        payload: JSON-serialisable snapshot of the task arguments.
        user_id: Optional UUID of the user triggering the job.

    Returns:
        The persisted ``Job`` instance (status = ``queued``).
    """
    job = Job(task_name=task_name, payload=payload, user_id=user_id, status='queued')
    session.add(job)
    await session.flush()
    return job
