"""Stateless API with session-aware behavior — SessionCache recipe."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


class KeyValueBucket:
    """External store shared across nodes (think: Redis)."""

    def __init__(self) -> None:
        self._data: dict[str, object] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> object | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: object) -> None:
        with self._lock:
            self._data[key] = value

    def incr(self, key: str, n: int = 1) -> int:
        with self._lock:
            cur = int(self._data.get(key, 0) or 0)
            cur += n
            self._data[key] = cur
            return cur


@dataclass
class CachedEntry:
    value: object
    fetched_at: float


class SessionCache:
    """Read-through cache with a small TTL; falls through to `bucket` on miss."""

    def __init__(self, bucket: KeyValueBucket, *, ttl_s: float = 1.0) -> None:
        self._bucket = bucket
        self.ttl_s = ttl_s
        self._local: dict[str, CachedEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str, *, now: float) -> object | None:
        with self._lock:
            entry = self._local.get(key)
            if entry is not None and now - entry.fetched_at < self.ttl_s:
                return entry.value
        v = self._bucket.get(key)
        with self._lock:
            self._local[key] = CachedEntry(value=v, fetched_at=now)
        return v

    def set(self, key: str, value: object, *, now: float) -> None:
        self._bucket.set(key, value)
        with self._lock:
            self._local[key] = CachedEntry(value=value, fetched_at=now)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._local.pop(key, None)


class Node:
    """Stateless API node. State lives in the shared `bucket`; a per-node
    cache speeds up reads but is never the source of truth.
    """

    def __init__(self, node_id: str, bucket: KeyValueBucket,
                 *, ttl_s: float = 1.0) -> None:
        self.node_id = node_id
        self._bucket = bucket
        self.cache = SessionCache(bucket, ttl_s=ttl_s)

    def incr_quota(self, caller: str, *, now: float) -> int:
        """Increment the per-caller request count in the shared store."""
        count = self._bucket.incr(f"rate:{caller}")
        self.cache.set(f"rate:{caller}", count, now=now)
        return count

    def get_rate(self, caller: str, *, now: float) -> int:
        v = self.cache.get(f"rate:{caller}", now=now)
        return int(v or 0)

    def set_cursor(self, caller: str, cursor: int, *, now: float) -> None:
        self.cache.set(f"cursor:{caller}", cursor, now=now)

    def get_cursor(self, caller: str, *, now: float) -> int:
        v = self.cache.get(f"cursor:{caller}", now=now)
        return int(v or 0)

    def flag(self, caller: str, name: str, *, now: float) -> bool:
        v = self.cache.get(f"flag:{caller}:{name}", now=now)
        return bool(v)

    def set_flag(self, caller: str, name: str, value: bool, *, now: float) -> None:
        self.cache.set(f"flag:{caller}:{name}", value, now=now)
