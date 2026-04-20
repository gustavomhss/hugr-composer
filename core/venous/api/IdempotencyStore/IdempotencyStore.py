from __future__ import annotations


class IdempotencyStore:
    """Thread-safe in-memory idempotency store for batch requests.

    Attributes:
        _store: Internal dict mapping keys to cached results.
        _lock: Thread lock protecting concurrent access.
    """

    def __init__(self) -> None:
        self._store: dict[str, _Any] = {}
        self._lock = _threading.Lock()

    def get(self, key: str) -> _Any | None:
        """Return cached result for *key*, or None."""
        with self._lock:
            return self._store.get(key)

    def put(self, key: str, result: _Any) -> None:
        """Store *result* under *key*."""
        with self._lock:
            self._store[key] = result

    def seen(self, key: str) -> bool:
        """Return True if *key* was already processed."""
        with self._lock:
            return key in self._store
