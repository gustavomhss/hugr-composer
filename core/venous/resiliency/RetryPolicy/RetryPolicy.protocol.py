"""Protocol for RetryPolicy — generated from RetryPolicy.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Awaitable, Callable

@runtime_checkable
class RetryPolicy(Protocol):
    """RetryPolicy primitive — SRE-grade retry with exponential backoff, jitter, budget."""

    def should_retry(self, attempt: int, exc: BaseException) -> bool: ...
    def next_delay_ms(self, attempt: int) -> int: ...
    async def execute(self, fn: Callable[[], Awaitable[T]]) -> T: ...
