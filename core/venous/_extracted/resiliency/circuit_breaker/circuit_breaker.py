from __future__ import annotations
from collections.abc import Callable
from typing import Any
import functools


def circuit_breaker(service_name: str, failure_threshold: int=5, recovery_timeout_seconds: int=30, half_open_max_calls: int=3, failure_window_seconds: int=60) -> Callable:
    """Decorator wrapping an async function with circuit breaker logic.

    Args:
        service_name: Logical name of the downstream service.
        failure_threshold: Failures in window to trip the circuit.
        recovery_timeout_seconds: Seconds before entering HALF_OPEN.
        half_open_max_calls: Probe calls allowed in HALF_OPEN.
        failure_window_seconds: Sliding window width in seconds.

    Returns:
        Decorator that wraps the target function.
    """

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            state = await _get_state(service_name)
            if state == CircuitState.OPEN:
                if not await _should_probe(service_name, recovery_timeout_seconds):
                    raise CircuitOpenError(f'Circuit OPEN for {service_name!r} — fast-fail')
                await _set_state(service_name, CircuitState.HALF_OPEN)
            try:
                result = await func(*args, **kwargs)
                await _on_success(service_name, state, half_open_max_calls)
                return result
            except Exception:
                await _on_failure(service_name, failure_threshold, recovery_timeout_seconds, failure_window_seconds)
                raise
        return wrapper
    return decorator
