"""Protocol for InboxDeduplicator — generated from InboxDeduplicator.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Callable, Iterator

@runtime_checkable
class InboxDeduplicator(Protocol):
    """InboxDeduplicator primitive — Richardson/Kleppmann idempotent-consumer dedupe."""

    def seen(self, message_id: str, consumer: str) -> bool: ...
    def record(self, message_id: str, consumer: str) -> None: ...
    def purge_older_than(self, iso_timestamp: str) -> int: ...
