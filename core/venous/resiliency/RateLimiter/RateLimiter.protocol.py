"""Protocol for RateLimiter — generated from RateLimiter.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class RateLimiter(Protocol):
    """RateLimiter primitive — per-key admission governor over a rolling window."""

    async def acquire(self, key: str, cost: int, wait_ms: int) -> bool: ...
    def try_acquire(self, key: str, cost: int) -> bool: ...
    def current_rate(self, key: str) -> float: ...
