from __future__ import annotations
from collections.abc import Awaitable
from collections.abc import Callable


def scheduled_job(cron: str, *, name: str | None=None) -> Callable[[Callable[[], Awaitable[None]]], Callable[[], Awaitable[None]]]:
    """Decorator that registers an async function as a cron job.

    Args:
        cron: Cron expression (5-field: minute hour day month dow).
        name: Optional job name (defaults to the function name).

    Returns:
        The original function, unchanged.
    """

    def wrap(fn: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
        _JOBS.append(ScheduledJob(cron=cron, name=name or fn.__name__, func=fn))
        return fn
    return wrap
