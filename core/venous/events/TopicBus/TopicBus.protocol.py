"""Protocol for TopicBus — generated from TopicBus.py."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable
from collections.abc import Awaitable, Callable, Mapping

@runtime_checkable
class TopicBus(Protocol):
    """TopicBus primitive — publish/subscribe facade over a broker topic."""

    async def publish(self, topic: str, envelope: EventEnvelope) -> None: ...
    def subscribe(self, topic: str, group: str, handler: Callable[[EventEnvelope, Ack, Nack], Awaitable[None]]) -> None: ...
