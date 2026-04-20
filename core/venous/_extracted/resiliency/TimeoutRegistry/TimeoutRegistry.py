from __future__ import annotations


class TimeoutRegistry:
    """Registry that holds one AdaptiveTimeout per downstream dependency.

    Thread-safe for read; concurrent writes are idempotent (same key
    returns the same tracker once created).
    """

    def __init__(self, window_size: int=100, floor_ms: float=100.0, ceiling_ms: float=10000.0) -> None:
        """Initialise an empty registry with shared defaults.

        Args:
            window_size: Sliding window size for all trackers.
            floor_ms: Minimum timeout in ms for all trackers.
            ceiling_ms: Maximum timeout in ms for all trackers.
        """
        self._window_size = window_size
        self._floor_ms = floor_ms
        self._ceiling_ms = ceiling_ms
        self._trackers: dict[str, 'AdaptiveTimeout'] = {}

    def get_or_create(self, name: str) -> 'AdaptiveTimeout':
        """Return the AdaptiveTimeout for *name*, creating it if absent.

        Args:
            name: Downstream dependency name (e.g. 'stripe_api').

        Returns:
            ``AdaptiveTimeout`` instance for this dependency.
        """
        if name not in self._trackers:
            from app.resilience.adaptive_timeout import AdaptiveTimeout
            self._trackers[name] = AdaptiveTimeout(name=name, window_size=self._window_size, floor_ms=self._floor_ms, ceiling_ms=self._ceiling_ms)
        return self._trackers[name]

    def all_stats(self) -> dict[str, dict[str, float]]:
        """Return stats for every registered dependency.

        Returns:
            Dict mapping dependency name → stats dict from
            ``AdaptiveTimeout.get_stats()``.
        """
        return {name: t.get_stats() for name, t in self._trackers.items()}

    def names(self) -> list[str]:
        """Return sorted list of registered dependency names."""
        return sorted(self._trackers)
