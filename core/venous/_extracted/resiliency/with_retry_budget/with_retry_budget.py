from __future__ import annotations
from collections.abc import Callable
from typing import Any
import functools


def with_retry_budget(service: str, ratio: float=0.1, window_s: float=60.0, min_requests: int=10) -> Callable:
    """Decorator that gates retries through a global retry budget.

    Records every call as a request.  The decorated function is
    expected to only be called when a retry is intended — each
    invocation also records a retry and raises ``BudgetExhaustedError``
    if the budget is exhausted.

    Args:
        service: Logical service name (shared budget across instances).
        ratio: Maximum retry fraction before blocking (default 0.10).
        window_s: Sliding window width in seconds (default 60).
        min_requests: Warm-up count before enforcing budget.

    Returns:
        Decorator wrapping the target async function.
    """

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            budget = get_retry_budget(service, ratio=ratio, window_s=window_s, min_requests=min_requests)
            budget.record_request()
            if not budget.can_retry():
                raise BudgetExhaustedError(f'Retry budget exhausted for {service!r} ({budget.current_ratio():.1%} >= {ratio:.1%})')
            budget.record_retry()
            return await func(*args, **kwargs)
        return wrapper
    return decorator
