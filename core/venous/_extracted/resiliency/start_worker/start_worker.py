from __future__ import annotations
from typing import Any


async def start_worker() -> Any:
    """Create and start the Temporal worker (module-level singleton).

    Connects to the Temporal server, creates the worker, and starts
    polling.  Caches the worker so ``stop_worker()`` can shut it down.

    Returns:
        The running ``temporalio.worker.Worker`` instance.
    """
    global _worker
    from app.workflows.client import get_client
    client = await get_client()
    factory = WorkerFactory(task_queue=settings.TEMPORAL_TASK_QUEUE)
    _worker = await factory.create(client)
    await _worker.start()
    logger.info('Temporal worker started')
    return _worker
