from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Any
import os


class PubSubManager:
    """Unified pub/sub facade that selects backend based on configuration.

    Chooses ``RedisPubSubBackend`` when ``REDIS_URL`` is set and
    ``redis`` is importable; otherwise falls back to
    ``MemoryPubSubBackend``.

    Usage::

        mgr = get_pubsub_manager()
        await mgr.publish("items", payload)

        async for event in mgr.subscribe("items"):
            yield event
    """

    def __init__(self) -> None:
        """Select backend based on environment."""
        self._backend = self._choose_backend()

    def _choose_backend(self) -> MemoryPubSubBackend | RedisPubSubBackend:
        """Return the best available backend.

        Returns:
            ``RedisPubSubBackend`` if redis is available, else
            ``MemoryPubSubBackend``.
        """
        redis_url = os.getenv('REDIS_URL', '')
        if redis_url:
            try:
                import redis.asyncio
                return RedisPubSubBackend(redis_url)
            except ImportError:
                logger.warning('redis not installed — using in-process PubSub.')
        return MemoryPubSubBackend()

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish *payload* to *topic*.

        Args:
            topic: Channel / event type name.
            payload: Serialisable event data.
        """
        await self._backend.publish(topic, payload)

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Yield events for *topic* from the active backend.

        Args:
            topic: Channel / event type name.

        Yields:
            Event payloads in arrival order.
        """
        async for event in self._backend.subscribe(topic):
            yield event
