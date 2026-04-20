from __future__ import annotations
from typing import Any


async def cleanup_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """Example scheduled cleanup task (no task arguments).

    Designed to be invoked on a cron-like schedule (e.g. from an
    external scheduler enqueuing it periodically).  In production,
    replace the body with real cleanup logic (soft-deleted row
    purge, expired token sweep, etc.).

    Args:
        ctx: arq worker context dict.

    Returns:
        Dict with ``status``, ``cleaned``, and the executing ``job_id``.
    """
    job_id = ctx.get('job_id', 'unknown')
    logger.info('cleanup_task executing', extra={'job_id': job_id})
    return {'status': 'ok', 'cleaned': 0, 'job_id': job_id}
