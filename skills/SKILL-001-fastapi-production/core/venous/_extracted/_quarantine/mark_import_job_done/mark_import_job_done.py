from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import json
import uuid


async def mark_import_job_done(session: AsyncSession, job_id: uuid.UUID, processed: int, failed: int, error_rows: list[dict[str, Any]]) -> None:
    """Mark an ImportJob as done, saving the error report inline as JSON.

    Args:
        session: Async SQLAlchemy session.
        job_id: UUID of the job.
        processed: Final processed count.
        failed: Final failed count.
        error_rows: Rows that failed validation (stored in error_report_url field).
    """
    job = await get_import_job(session, job_id)
    if job is None:
        return
    job.status = 'done'
    job.processed = processed
    job.failed = failed
    if error_rows:
        job.error_report_url = f'inline:{json.dumps(error_rows[:1000])}'
    await session.commit()
