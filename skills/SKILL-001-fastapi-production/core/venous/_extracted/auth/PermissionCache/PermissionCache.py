from __future__ import annotations
from collections import OrderedDict
from uuid import UUID
import asyncio
import json
import time


class PermissionCache:
    """Thread-safe async LRU permission cache.

    Attributes:
        _ttl: Cache entry TTL in seconds.
        _store: OrderedDict mapping (user_id, tenant_id) → (timestamp, perms).
        _lock: Async lock protecting the store.
        _listener_task: Background asyncio task for Redis pub/sub.
    """

    def __init__(self, ttl: float=_TTL) -> None:
        self._ttl = ttl
        self._store: OrderedDict[tuple[UUID, UUID | None], tuple[float, set[str]]] = OrderedDict()
        self._lock = asyncio.Lock()
        self._listener_task: asyncio.Task | None = None

    async def get(self, user_id: UUID, tenant_id: UUID | None) -> set[str] | None:
        """Return cached permissions or None if missing/expired.

        Args:
            user_id: The user's UUID.
            tenant_id: Optional tenant scope.

        Returns:
            Copy of the cached permission set, or ``None``.
        """
        async with self._lock:
            entry = self._store.get((user_id, tenant_id))
            if entry is None:
                return None
            ts, perms = entry
            if time.monotonic() - ts > self._ttl:
                del self._store[user_id, tenant_id]
                return None
            self._store.move_to_end((user_id, tenant_id))
            return set(perms)

    async def set(self, user_id: UUID, tenant_id: UUID | None, perms: set[str]) -> None:
        """Store permissions for (user_id, tenant_id), evicting LRU if full.

        Args:
            user_id: The user's UUID.
            tenant_id: Optional tenant scope.
            perms: Permission code set to cache.
        """
        async with self._lock:
            key = (user_id, tenant_id)
            self._store[key] = (time.monotonic(), set(perms))
            self._store.move_to_end(key)
            while len(self._store) > MAX_SIZE:
                self._store.popitem(last=False)

    async def invalidate_user(self, user_id: UUID) -> None:
        """Remove all cache entries for *user_id* across all tenants.

        Args:
            user_id: User whose cache entries should be cleared.
        """
        async with self._lock:
            for k in list(self._store):
                if k[0] == user_id:
                    del self._store[k]

    async def clear(self) -> None:
        """Clear all cache entries (broadcast invalidation)."""
        async with self._lock:
            self._store.clear()

    async def start_listener(self, redis) -> None:
        """Start a background task that listens for Redis invalidation messages.

        Args:
            redis: An async Redis client (``redis.asyncio.Redis``).
        """

        async def _run() -> None:
            ps = redis.pubsub()
            await ps.subscribe(INVALIDATION_CHANNEL)
            async for msg in ps.listen():
                if msg.get('type') != 'message':
                    continue
                try:
                    payload = json.loads(msg['data'])
                    uid = payload.get('user_id')
                    if uid == '*':
                        await self.clear()
                    else:
                        await self.invalidate_user(UUID(uid))
                except Exception:
                    pass
        self._listener_task = asyncio.create_task(_run())
