from __future__ import annotations


class AdaptiveTimeout:
    """Tracks latency statistics for a single downstream dependency.

    Maintains a sliding window of latency samples and computes p50/p95/p99.
    The computed timeout is ``p99 * 1.5`` clamped between floor and ceiling.

    Args:
        name: Logical name of the downstream dependency.
        window_size: Number of samples in the sliding window.
        multiplier: p99 multiplier for timeout calculation.
        floor_ms: Minimum timeout in milliseconds.
        ceiling_ms: Maximum timeout in milliseconds.
    """

    def __init__(self, name: str, window_size: int=100, multiplier: float=1.5, floor_ms: float=_DEFAULT_FLOOR_MS, ceiling_ms: float=_DEFAULT_CEILING_MS) -> None:
        """Initialise AdaptiveTimeout with configurable parameters."""
        self.name = name
        self._window_size = window_size
        self._multiplier = multiplier
        self._floor_ms = floor_ms
        self._ceiling_ms = ceiling_ms
        self._samples: list[float] = []

    def record(self, latency_ms: float) -> None:
        """Record a latency sample and trim the window.

        Args:
            latency_ms: Observed latency in milliseconds.
        """
        self._samples.append(latency_ms)
        if len(self._samples) > self._window_size:
            self._samples = self._samples[-self._window_size:]

    def get_timeout_s(self) -> float:
        """Return the current adaptive timeout in seconds.

        Returns:
            Timeout in seconds, clamped between floor and ceiling.
        """
        if not self._samples:
            return self._ceiling_ms / 1000.0
        p99 = self._percentile(0.99)
        raw_ms = p99 * self._multiplier
        clamped_ms = max(self._floor_ms, min(self._ceiling_ms, raw_ms))
        return clamped_ms / 1000.0

    def get_stats(self) -> dict[str, float]:
        """Return current percentile statistics.

        Returns:
            Dict with p50, p95, p99 in milliseconds and current_timeout_s.
        """
        if not self._samples:
            return {'p50': 0.0, 'p95': 0.0, 'p99': 0.0, 'current_timeout_s': self._ceiling_ms / 1000.0, 'sample_count': 0}
        return {'p50': self._percentile(0.5), 'p95': self._percentile(0.95), 'p99': self._percentile(0.99), 'current_timeout_s': self.get_timeout_s(), 'sample_count': len(self._samples)}

    def _percentile(self, p: float) -> float:
        """Compute the *p*-th percentile of current samples.

        Args:
            p: Percentile as a fraction (e.g. 0.99 for p99).
        """
        sorted_s = sorted(self._samples)
        idx = max(0, int(len(sorted_s) * p) - 1)
        return sorted_s[idx]
