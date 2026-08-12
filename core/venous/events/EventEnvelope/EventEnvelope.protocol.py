"""Protocol for EventEnvelope — generated from EventEnvelope.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Mapping

@runtime_checkable
class EventEnvelopeProtocol(Protocol):
    """CloudEvents 1.0.2 canonical envelope."""

    def dedup_key(self) -> tuple[str, str]: ...
    def retry(self) -> EventEnvelope: ...

@runtime_checkable
class InMemoryDedupSetProtocol(Protocol):
    """Reference dedup oracle. Not thread-safe; wrap in a lock for concurrent use."""

    def accept(self, envelope: EventEnvelope) -> bool: ...
    def size(self) -> int: ...
