"""Protocol for Aggregate — generated from Aggregate.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class Aggregate(Protocol):
    """Aggregate primitive — Evans/Vernon DDD transactional-consistency boundary."""

    def id(self) -> ID_co: ...
    def version(self) -> int: ...
    def pull_events(self) -> Iterable[object]: ...
