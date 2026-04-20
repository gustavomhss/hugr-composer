from __future__ import annotations
from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def time_saga_step(saga_type: str, step_name: str) -> Generator[None, None, None]:
    """Context manager that records step duration histogram.

    Args:
        saga_type: Saga class name.
        step_name: Step method name.

    Yields:
        None.
    """
    if not _PROMETHEUS_AVAILABLE:
        yield
        return
    with saga_step_duration.labels(saga_type=saga_type, step_name=step_name).time():
        yield
