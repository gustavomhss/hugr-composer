from __future__ import annotations


class MeterEventBuffer:
    """Thread-safe in-memory buffer for meter events pending Stripe sync."""

    def __init__(self, max_size: int=500) -> None:
        """Initialise buffer with configurable max size."""
        self._events: list[MeterEvent] = []
        self._max_size = max_size

    def add(self, event: MeterEvent) -> None:
        """Append event; silently drops oldest when buffer is full."""
        if len(self._events) >= self._max_size:
            self._events.pop(0)
        self._events.append(event)

    def drain(self, batch_size: int) -> list[MeterEvent]:
        """Remove and return up to batch_size events."""
        batch = self._events[:batch_size]
        self._events = self._events[batch_size:]
        return batch

    @property
    def size(self) -> int:
        """Return the current number of buffered events."""
        return len(self._events)
