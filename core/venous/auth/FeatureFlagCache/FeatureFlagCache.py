from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict

# Module-level tuning constants (see FeatureFlagCache.md). Feature-flag reads
# vastly outnumber writes, so a short TTL bounds staleness while a capacity cap
# bounds memory; invalidation messages arrive on a dedicated pubsub channel.
CACHE_TTL_SECONDS: float = 300.0
MAX_CACHE_SIZE: int = 1000
INVALIDATION_CHANNEL: str = "feature_flags:invalidate"


class FeatureFlagCache:
    """Bounded in-process LRU cache with TTL for feature-flag payloads.

    Attributes:
        CACHE_TTL_SECONDS: Entry lifetime in seconds (module constant).
        MAX_CACHE_SIZE: Maximum entries before LRU eviction (module constant).
    """

    def __init__(self) -> None:
        self._store: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._invalidation_task: asyncio.Task | None = None

    async def get(self, key: str) -> dict | None:
        """Return cached payload, or None if missing/expired.

        Args:
            key: Flag key string.

        Returns:
            Cached dict payload, or None.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if time.monotonic() - stored_at > CACHE_TTL_SECONDS:
                del self._store[key]
                return None
            self._store.move_to_end(key)
            return value

    async def set(self, key: str, value: dict) -> None:
        """Store a flag payload, evicting LRU entries if at capacity.

        Args:
            key: Flag key string.
            value: Serialisable flag payload dict.
        """
        async with self._lock:
            self._store[key] = (time.monotonic(), value)
            self._store.move_to_end(key)
            while len(self._store) > MAX_CACHE_SIZE:
                self._store.popitem(last=False)

    async def invalidate(self, key: str) -> None:
        """Evict a single key from the cache.

        Args:
            key: Flag key to evict, or '*' to clear all.
        """
        async with self._lock:
            if key == '*':
                self._store.clear()
            else:
                self._store.pop(key, None)

    async def clear(self) -> None:
        """Evict all entries from the cache."""
        async with self._lock:
            self._store.clear()

    async def start_invalidation_listener(self, redis) -> None:
        """Subscribe to Redis pubsub and evict keys on incoming messages.

        Args:
            redis: Connected ``redis.asyncio.Redis`` client.
        """

        async def _listen() -> None:
            pubsub = redis.pubsub()
            await pubsub.subscribe(INVALIDATION_CHANNEL)
            async for message in pubsub.listen():
                if message.get('type') != 'message':
                    continue
                try:
                    payload = json.loads(message['data'])
                except (json.JSONDecodeError, TypeError):
                    continue
                key = payload.get('key') or payload.get('flag_key')
                if key:
                    await self.invalidate(key)
        self._invalidation_task = asyncio.create_task(_listen())

    async def stop(self) -> None:
        """Cancel the background invalidation listener task."""
        if self._invalidation_task:
            self._invalidation_task.cancel()
