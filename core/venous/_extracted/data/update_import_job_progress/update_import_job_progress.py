from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def update_import_job_progress(session: AsyncSession, job_id: uuid.UUID, processed: int, failed: int, total_rows: int) -> None:
    """Update progress counters on an active ImportJob.

    Args:
        session: Async SQLAlchemy session.
        job_id: UUID of the job to update.
        processed: Rows successfully committed so far.
        failed: Rows rejected by validation.
        total_rows: Total rows parsed from the file.
    """
    job = await get_import_job(session, job_id)
    if job is None:
        logger.warning('update_import_job_progress: job %s not found', job_id)
        return
    job.status = 'processing'
    job.processed = processed
    job.failed = failed
    job.total_rows = total_rows
    await session.commit()
