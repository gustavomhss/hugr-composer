"""Protocol for Bulkhead — generated from Bulkhead.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import AsyncIterator, Callable, Mapping

@runtime_checkable
class Bulkhead(Protocol):
    """Partitioned concurrency limiter — bounded slots + bounded wait."""

    async def submit(self) -> T: ...
    def available_permits(self) -> int: ...
