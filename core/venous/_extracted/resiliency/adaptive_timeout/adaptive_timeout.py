from __future__ import annotations
from collections.abc import Callable
from typing import Any
import asyncio
import functools
import time


def adaptive_timeout(dependency: str, registry: TimeoutRegistry | None=None) -> Callable:
    """Decorator that wraps an async function with an adaptive timeout.

    The timeout is auto-adjusted based on observed latency of *dependency*.
    Each call records its latency so future calls benefit from the data.

    Args:
        dependency: Logical name of the downstream dependency.
        registry: Optional custom TimeoutRegistry (uses global if None).

    Returns:
        Decorator wrapping the async function with timeout + latency recording.
    """

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _is_enabled():
                return await func(*args, **kwargs)
            reg = registry or get_timeout_registry()
            tracker = reg.get_or_create(dependency)
            timeout_s = tracker.get_timeout_s()
            t0 = time.monotonic()
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_s)
                latency_ms = (time.monotonic() - t0) * 1000.0
                tracker.record(latency_ms)
                return result
            except asyncio.TimeoutError:
                latency_ms = timeout_s * 1000.0
                tracker.record(latency_ms)
                logger.warning('Adaptive timeout fired for %s after %.0fms', dependency, latency_ms)
                raise
        return wrapper
    return decorator
