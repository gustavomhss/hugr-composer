"""Adaptive timeout calculator."""

from __future__ import annotations
import statistics

_DEFAULT_FLOOR_MS = 100

class AdaptiveTimeout:
    """Calculates adaptive timeouts based on observed latency."""

    def __init__(self, floor_ms: int = _DEFAULT_FLOOR_MS):
        self.floor_ms = floor_ms
        self.samples = []

    def record(self, latency_ms: float):
        self.samples.append(latency_ms)
        if len(self.samples) > 100:
            self.samples.pop(0)

    def get_timeout(self) -> int:
        if not self.samples:
            return self.floor_ms
        return max(self.floor_ms, int(statistics.mean(self.samples) * 3))
