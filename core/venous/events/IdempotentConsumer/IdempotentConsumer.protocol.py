"""Protocol for IdempotentConsumer — generated from IdempotentConsumer.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable

@runtime_checkable
class IdempotentConsumer(Protocol):
    """IdempotentConsumer primitive — Richardson/Kleppmann exactly-once-effect consumer."""

    def key_for(self, message: object) -> str: ...
    def handle(self, message: object) -> None: ...
    def on_duplicate(self, message: object) -> None: ...
