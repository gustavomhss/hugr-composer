from __future__ import annotations
from typing import Any
import json


async def set_export_progress(redis: 'aioredis.Redis', job_id: str, status: ExportStatus, *, rows_written: int=0, total_rows: int=0, download_url: str | None=None, error: str | None=None) -> None:
    """Write job progress to Redis with a 25-hour TTL.

    Args:
        redis: Async Redis client.
        job_id: Unique export job identifier.
        status: Current lifecycle state.
        rows_written: Rows streamed to storage so far.
        total_rows: Total rows expected (0 if unknown).
        download_url: Presigned download URL, set when status=COMPLETE.
        error: Error message, set when status=FAILED.
    """
    key = f'export_job:{job_id}'
    payload: dict[str, Any] = {'job_id': job_id, 'status': status.value, 'rows_written': rows_written, 'total_rows': total_rows}
    if download_url:
        payload['download_url'] = download_url
    if error:
        payload['error'] = error
    await redis.setex(key, JOB_TTL_SECONDS, json.dumps(payload))
