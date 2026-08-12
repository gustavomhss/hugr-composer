"""Protocol for EventSourcedStore — generated from EventSourcedStore.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class EventSourcedStore(Protocol):
    """EventSourcedStore primitive — Fowler / Vernon / Richardson event sourcing."""

    def load(self, aggregate_id: str) -> Iterable[Any]: ...
    def append(self, aggregate_id: str, expected_version: int, events: Iterable[Any]) -> int: ...
    def snapshot(self, aggregate_id: str, version: int, state: Any) -> None: ...
    def latest_snapshot(self, aggregate_id: str) -> Any: ...
