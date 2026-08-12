"""Protocol for TransactionalOutbox — generated from TransactionalOutbox.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Iterable

@runtime_checkable
class TransactionalOutbox(Protocol):
    """TransactionalOutbox primitive — Richardson Microservices Patterns dual-write guard."""

    def enqueue(self, destination: str, payload: Any, key: str) -> None: ...
    def pending(self, limit: int) -> Iterable[dict[str, object]]: ...
    def mark_published(self, message_id: str) -> None: ...
    def mark_failed(self, message_id: str, reason: str) -> None: ...
