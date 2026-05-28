from __future__ import annotations
from collections import defaultdict
import time


class AttackPatternRegistry:
    """Thread-safe (GIL) in-memory registry of security events.

    Provides per-type event storage and frequency queries used
    by the learning-mode baseline.
    """

    def __init__(self, max_events: int=10000) -> None:
        """Initialise registry with bounded event storage.

        Args:
            max_events: Maximum events to retain (oldest evicted first).
        """
        self._events: list[SecurityEvent] = []
        self._counts: dict[str, int] = defaultdict(int)
        self._max_events = max_events

    def record(self, event: SecurityEvent) -> None:
        """Record a security event, evicting oldest when capacity exceeded.

        Args:
            event: The security event to store.
        """
        if len(self._events) >= self._max_events:
            self._events = self._events[-(self._max_events // 2):]
        self._events.append(event)
        self._counts[event.attack_type] += 1
        if event.blocked:
            logger.warning('SENTINEL_ATTACK blocked=%s type=%s path=%s snippet=%r', event.blocked, event.attack_type, event.request_path, event.payload_snippet[:80])
        else:
            logger.info('SENTINEL_ATTACK blocked=%s type=%s path=%s snippet=%r', event.blocked, event.attack_type, event.request_path, event.payload_snippet[:80])

    def count(self, attack_type: str) -> int:
        """Return total recorded events for a given attack type.

        Args:
            attack_type: e.g. 'sql_injection'.

        Returns:
            Integer count of events of that type.
        """
        return self._counts[attack_type]

    def recent(self, attack_type: str, since_seconds: float=3600.0) -> list[SecurityEvent]:
        """Return events of *attack_type* newer than *since_seconds*.

        Args:
            attack_type: Event category to filter.
            since_seconds: Window in seconds from now.

        Returns:
            List of SecurityEvent objects within the window.
        """
        cutoff = time.time() - since_seconds
        return [e for e in self._events if e.attack_type == attack_type and e.timestamp >= cutoff]
