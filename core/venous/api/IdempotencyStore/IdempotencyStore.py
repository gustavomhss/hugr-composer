"""Thread-safe in-memory idempotency store for batch + webhook replay protection.

Invariants cited here:

- IS_INV_01 — get-after-put: ``put(k, v)`` makes ``get(k) == v``; keys
  that were never put return ``None``.
- IS_INV_02 — seen / get agreement: ``seen(k)`` is ``True`` iff a value
  (including ``None``) has been put under ``k``. Membership and
  retrieval never disagree.
- IS_INV_03 — concurrent-write serialisation: no write is dropped and
  no value is torn under concurrent ``put`` calls; the internal lock
  is the atomicity boundary.
"""
from __future__ import annotations

import threading
from typing import Any


class IdempotencyStore:
    """Thread-safe in-memory idempotency store for batch requests.

    Attributes:
        _store: Internal dict mapping keys to cached results.
        _lock: Thread lock protecting concurrent access.
    """

    __slots__ = ("_store", "_lock")

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        self._lock: threading.Lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return cached result for *key*, or ``None`` when never put.

        Note: a legitimate ``None`` result and "never put" return the
        same value. Use ``seen`` to distinguish.
        """
        with self._lock:
            return self._store.get(key)

    def put(self, key: str, result: Any) -> None:
        """Store *result* under *key*. Overwrites any prior value."""
        with self._lock:
            self._store[key] = result

    def seen(self, key: str) -> bool:
        """Return ``True`` iff *key* has been put (even with value ``None``)."""
        with self._lock:
            return key in self._store


__all__ = ["IdempotencyStore"]
