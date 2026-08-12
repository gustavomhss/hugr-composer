"""Protocol for PubSub — generated from PubSub.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import AsyncIterator

@runtime_checkable
class PubSub(Protocol):
    """The minimum fanout pub/sub surface."""

    async def publish(self, topic: str, payload: Any) -> None: ...
    def subscribe(self, topic: str) -> AsyncIterator[Any]: ...
