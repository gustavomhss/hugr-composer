from __future__ import annotations
import asyncio


async def schedule_retention_worker(session_factory: object, interval_s: int=_DEFAULT_INTERVAL_S) -> None:
    """Loop forever, running a retention cycle every *interval_s* seconds.

    Intended to be started with ``asyncio.create_task(schedule_retention_worker(...))``.
    All exceptions are caught and logged so the loop never crashes the process.

    Args:
        session_factory: Async session factory.
        interval_s: Seconds between retention cycles (default 3600).
    """
    while True:
        try:
            await run_retention_cycle(session_factory)
        except Exception as exc:
            logger.error('retention_worker_error', extra={'error': str(exc)})
        await asyncio.sleep(interval_s)
