from __future__ import annotations
from typing import Any


async def enqueue(task_name: str, *args: Any, _defer_by: int | None=None, **kwargs: Any) -> str:
    """Enqueue *task_name* on the arq queue and return the job id.

    Args:
        task_name: Registered function name (must appear in
            ``TASK_REGISTRY``).
        *args: Positional arguments forwarded to the task function.
        _defer_by: Optional delay in seconds before the job becomes
            eligible for execution.  ``None`` means run ASAP.
        **kwargs: Keyword arguments forwarded to the task function.

    Returns:
        The arq job id (string).  Callers can use this id to poll
        ``GET /jobs/{job_id}/status``.

    Raises:
        RuntimeError: If arq returns no job (enqueue rejected).
    """
    pool = await get_pool()
    kw: dict[str, Any] = {}
    if _defer_by is not None:
        kw['_defer_by'] = _defer_by
    job = await pool.enqueue_job(task_name, *args, **kwargs, **kw)
    if job is None:
        raise RuntimeError(f'arq refused to enqueue task={task_name} (queue full or duplicate job id)')
    return job.job_id
