from __future__ import annotations
from collections.abc import AsyncIterator
from typing import Any
import json
import os


class RedisPubSubBackend:
    """Redis-backed pub/sub for multi-worker deployments.

    Redis is imported lazily so that ``app.main`` boots without
    the ``redis`` package installed. Falls back to ``MemoryPubSubBackend``
    when Redis is unavailable.

    Args:
        redis_url: Redis connection URL (default: ``REDIS_URL`` env var).
    """

    def __init__(self, redis_url: str | None=None) -> None:
        """Store the Redis URL for lazy connection."""
        self._url = redis_url or os.getenv('REDIS_URL', 'redis://localhost:6379/0')
        self._client: Any = None

    def _get_client(self) -> Any:
        """Return a lazy-loaded redis.asyncio client.

        Returns:
            A ``redis.asyncio.Redis`` client instance.

        Raises:
            ImportError: If the ``redis`` package is not installed.
        """
        if self._client is None:
            import redis.asyncio as aioredis
            self._client = aioredis.from_url(self._url, decode_responses=True)
        return self._client

    async def publish(self, topic: str, payload: Any) -> None:
        """Publish *payload* as JSON to Redis channel *topic*.

        Args:
            topic: Redis channel name.
            payload: Serialisable event data; serialised to JSON.
        """
        client = self._get_client()
        await client.publish(topic, json.dumps(payload))

    async def subscribe(self, topic: str) -> AsyncIterator[Any]:
        """Subscribe to Redis channel *topic* and yield decoded events.

        Args:
            topic: Redis channel name.

        Yields:
            Deserialised event payloads.
        """
        client = self._get_client()
        async with client.pubsub() as pubsub:
            await pubsub.subscribe(topic)
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    yield json.loads(message['data'])
