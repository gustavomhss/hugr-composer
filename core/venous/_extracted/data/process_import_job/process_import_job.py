from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def process_import_job(session: AsyncSession, job_id: uuid.UUID, content: bytes, filename: str, processor: ImportProcessor) -> None:
    """Run the full import pipeline for a job: parse → validate → batch.

    Updates the ImportJob record with progress, failure counts, and
    final status.  Captures exceptions and marks the job as failed rather
    than letting errors propagate unhandled.

    Args:
        session: Async SQLAlchemy session (caller manages lifecycle).
        job_id: UUID of the ImportJob row to update.
        content: Raw uploaded file bytes.
        filename: Original file name (used to detect CSV vs Excel).
        processor: ImportProcessor instance configured for this job.
    """
    try:
        if filename.lower().endswith(('.xlsx', '.xls')):
            rows = processor.parse_excel(content)
        else:
            rows = processor.parse_csv(content)
        valid_rows, error_rows = processor.validate_rows(rows)
        total = len(rows)
        await update_import_job_progress(session, job_id, 0, len(error_rows), total)
        processed = 0
        for i in range(0, len(valid_rows), processor.batch_size):
            batch = valid_rows[i:i + processor.batch_size]
            done = await processor.process_batch(session, batch)
            processed += done
            await update_import_job_progress(session, job_id, processed, len(error_rows), total)
        await mark_import_job_done(session, job_id, processed, len(error_rows), error_rows)
    except Exception as exc:
        logger.exception('process_import_job failed job_id=%s', job_id)
        await fail_import_job(session, job_id, str(exc))
