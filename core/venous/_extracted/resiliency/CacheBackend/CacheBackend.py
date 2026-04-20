from __future__ import annotations
from typing import Any


class CacheBackend:
    """Thin async wrapper around Redis with msgpack serialization.

    Args:
        redis: Connected async Redis client.
        default_ttl: Default key expiration in seconds.
    """

    def __init__(self, redis: 'Redis', default_ttl: int=300) -> None:
        self.redis = redis
        self.default_ttl = default_ttl

    async def get(self, key: str) -> Any:
        """Return deserialised value or None on miss / error.

        Args:
            key: Redis key to look up.
        """
        try:
            data = await self.redis.get(key)
            return msgpack.unpackb(data, raw=False) if data is not None else None
        except Exception:
            logger.warning('Cache GET failed for key=%s', key, exc_info=True)
            return None

    async def set(self, key: str, value: Any, *, ttl: int | None=None) -> bool:
        """Serialise *value* with msgpack and store in Redis.

        Args:
            key: Redis key.
            value: Python object to store.
            ttl: Expiration seconds; falls back to ``default_ttl``.
        """
        try:
            packed = msgpack.packb(value, use_bin_type=True)
            await self.redis.setex(key, ttl or self.default_ttl, packed)
            return True
        except Exception:
            logger.warning('Cache SET failed for key=%s', key, exc_info=True)
            return False

    async def delete(self, key: str) -> int:
        """Delete a single key.  Returns number of keys deleted.

        Args:
            key: Redis key to remove.
        """
        try:
            return await self.redis.delete(key)
        except Exception:
            logger.warning('Cache DELETE failed for key=%s', key, exc_info=True)
            return 0

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching *pattern* (SCAN-based, safe for production).

        Args:
            pattern: Redis glob pattern (e.g. ``cache:tenant1:items:*``).
        """
        deleted = 0
        try:
            async for key in self.redis.scan_iter(match=pattern, count=100):
                deleted += await self.redis.delete(key)
        except Exception:
            logger.warning('Cache DELETE_PATTERN failed pattern=%s', pattern, exc_info=True)
        return deleted

    async def stats(self) -> dict:
        """Return cache stats dict (hit_keys, memory_bytes, connected)."""
        try:
            info = await self.redis.info('memory')
            keyspace = await self.redis.info('keyspace')
            return {'connected': True, 'memory_used_bytes': info.get('used_memory', 0), 'memory_human': info.get('used_memory_human', 'N/A'), 'keyspace': keyspace}
        except Exception as exc:
            return {'connected': False, 'error': str(exc)}
