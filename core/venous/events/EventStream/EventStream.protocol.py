"""Protocol for EventStream — generated from EventStream.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterator, Mapping

@runtime_checkable
class EventStream(Protocol):
    """EventStream primitive — Kleppmann DDIA Ch. 11 / Richardson event logs."""

    def append(self, partition_key: str, event: Any) -> int: ...
    def read_from(self, partition_key: str, offset: int) -> Iterator[Any]: ...
    def tail(self, partition_key: str) -> int: ...
    def truncate_before(self, offset: int) -> None: ...
