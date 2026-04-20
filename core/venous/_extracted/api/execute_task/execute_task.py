from __future__ import annotations
import json


async def execute_task(ctx: dict, raw_id: str, task_type: str, params: str) -> None:
    """ARQ job: run the handler for *task_type* and update Redis state.

    Args:
        ctx: ARQ context dict (contains ``redis`` client).
        raw_id: Raw UUID string of the task (not encrypted).
        task_type: Registered task type identifier.
        params: JSON-encoded parameter dict.

    The handler is looked up via ``task_registry``; any exception sets
    status=failed.  The worker checks ``is_cancel_requested`` before
    executing and marks the task cancelled if the flag is set.
    """
    from app.core.task_manager import TaskManager, TaskStatus
    from app.core.task_registry import task_registry
    mgr = TaskManager(redis=ctx['redis'])
    if await mgr.is_cancel_requested(raw_id):
        await mgr.set_status(raw_id, TaskStatus.CANCELLED.value)
        return
    await mgr.set_status(raw_id, TaskStatus.RUNNING.value)
    parsed_params = json.loads(params)
    try:
        handler = task_registry.get(task_type)
        result = await handler(raw_id=raw_id, params=parsed_params)
        await mgr.set_result(raw_id, result)
    except Exception as exc:
        await mgr.set_error(raw_id, f'{type(exc).__name__}: {exc}')
        raise
