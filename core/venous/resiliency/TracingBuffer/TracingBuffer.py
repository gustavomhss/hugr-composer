from __future__ import annotations

import threading
from collections import deque
from typing import Any


class TracingBuffer:
    """Thread-safe ring buffer of the last N traced requests.

    Args:
        maxlen: Maximum number of request records to retain.
    """

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, entry: dict[str, Any]) -> None:
        """Append a request trace entry to the ring buffer.

        Args:
            entry: Dict with at minimum 'id', 'method', 'path',
                'status_code', 'total_ms', 'spans'.
        """
        with self._lock:
            self._buf.append(entry)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all buffered entries, newest-first."""
        with self._lock:
            return list(reversed(self._buf))

    def get_by_id(self, request_id: str) -> dict[str, Any] | None:
        """Return the entry with the given request ID, or None.

        Args:
            request_id: UUID string assigned when the request arrived.
        """
        with self._lock:
            for entry in self._buf:
                if entry.get("id") == request_id:
                    return entry
        return None

    def get_slow(self, percentile: float = 0.99) -> list[dict[str, Any]]:
        """Return requests at or above the given latency percentile.

        Args:
            percentile: Fraction (0-1) above which requests are 'slow'.
                Defaults to 0.99 (p99).
        """
        with self._lock:
            items = sorted(self._buf, key=lambda r: r.get("total_ms", 0))
        if not items:
            return []
        cutoff_idx = max(0, int(len(items) * percentile) - 1)
        threshold = items[cutoff_idx].get("total_ms", 0)
        return [r for r in items if r.get("total_ms", 0) >= threshold]

    def __len__(self) -> int:
        """Return current number of buffered entries."""
        return len(self._buf)
