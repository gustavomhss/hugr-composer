"""Protocol for TimeoutBudget — generated from TimeoutBudget.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterator

@runtime_checkable
class TimeoutBudget(Protocol):
    """Hierarchical monotonic deadline attached to an inbound request."""

    def remaining_ms(self) -> int: ...
    def for_call(self, max_ms: int) -> int: ...
    def expired(self) -> bool: ...
