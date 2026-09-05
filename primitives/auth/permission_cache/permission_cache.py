"""Permission cache with TTL."""

from __future__ import annotations

_TTL = 300

class PermissionCache:
    """In-memory permission cache with TTL."""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str):
        import time
        if key in self._cache and time.time() - self._timestamps.get(key, 0) < _TTL:
            return self._cache[key]
        return None

    def set(self, key: str, value):
        import time
        self._cache[key] = value
        self._timestamps[key] = time.time()
