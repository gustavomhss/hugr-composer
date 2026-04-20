from __future__ import annotations
from typing import Any
import uuid


async def dispatch_export_job(*, user_id: uuid.UUID, model: str, format: str, filters: dict[str, Any]) -> uuid.UUID:
    """Enqueue a background export job. Returns a new job_id UUID.

    The worker streams data to storage and emails the user a presigned URL.

    Args:
        user_id: UUID of the requesting user.
        model: Model name string (e.g. ``"Item"``).
        format: Export format — ``csv``, ``json``, ``xlsx``, or ``parquet``.
        filters: Dict of column name -> value filters applied at the worker.

    Returns:
        Newly generated ``job_id`` UUID.
    """
    from app.core.arq import enqueue_job
    job_id = uuid.uuid4()
    await enqueue_job('run_export', job_id=str(job_id), user_id=str(user_id), model=model, format=format, filters=filters)
    return job_id
