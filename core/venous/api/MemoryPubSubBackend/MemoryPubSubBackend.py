from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Any
import asyncio


class MemoryPubSubBackend:
    """In-process pub/sub using asyncio.Queue per subscriber.

    Suitable for single-worker deployments only. Events are NOT
    shared across processes or workers.
    """

    def __init__(self) -> None:
        """Initialise an empty subscriber registry."""
        self._subscribers: dict[str, list[asyncio.Queue[Any]]] = {}

    async def publish(self, topic: str, payload: Any) -> None:
        """Broadcast *payload* to all current subscribers of *topic*.

        Args:
            topic: Logical channel name (e.g. ``"items"``).
            payload: Serialisable event data.
        """
        queues = self._subscribers.get(topic, [])
        for q in list(queues):
            await q.put(payload)

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Yield events published to *topic* until the generator is closed.

        Args:
            topic: Logical channel name.

        Yields:
            Each event payload in arrival order.
        """
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.setdefault(topic, []).append(q)
        try:
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            subs = self._subscribers.get(topic, [])
            if q in subs:
                subs.remove(q)
