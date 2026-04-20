from __future__ import annotations
import time


class LoadShedder:
    """Monitors p99 latency and decides when to shed load.

    Maintains a sliding window of recent latency samples and computes
    the p99. When p99 exceeds the threshold the shedder enters
    degradation tiers; it exits when the window clears below the threshold.

    Args:
        p99_threshold_ms: p99 latency in ms above which shedding starts.
        window_size: Number of samples to keep in the sliding window.
        recovery_window_s: Seconds of clean window before recovering.
    """

    def __init__(self, p99_threshold_ms: float=500.0, window_size: int=100, recovery_window_s: float=30.0) -> None:
        """Initialise the LoadShedder with configurable thresholds."""
        self._threshold_ms = p99_threshold_ms
        self._window_size = window_size
        self._recovery_s = recovery_window_s
        self._samples: collections.deque[float] = collections.deque(maxlen=window_size)
        self._shed_since: float | None = None
        self._tier = DegradationTier.NORMAL

    def record_latency(self, latency_ms: float) -> None:
        """Record a new latency sample and update the degradation tier.

        Args:
            latency_ms: Request latency in milliseconds.
        """
        self._samples.append(latency_ms)
        self._update_tier()

    def get_p99(self) -> float:
        """Return the current p99 latency from the sliding window.

        Returns:
            p99 latency in milliseconds, or 0.0 if no samples.
        """
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = max(0, int(len(sorted_samples) * 0.99) - 1)
        return sorted_samples[idx]

    def is_shedding(self) -> bool:
        """Return True when the service is currently shedding load."""
        return self._tier != DegradationTier.NORMAL

    def get_tier(self) -> DegradationTier:
        """Return the current degradation tier."""
        return self._tier

    def _update_tier(self) -> None:
        """Recompute degradation tier based on current p99."""
        p99 = self.get_p99()
        now = time.monotonic()
        if p99 >= self._threshold_ms * 2.0:
            new_tier = DegradationTier.TIER_3
        elif p99 >= self._threshold_ms * 1.5:
            new_tier = DegradationTier.TIER_2
        elif p99 >= self._threshold_ms:
            new_tier = DegradationTier.TIER_1
        else:
            new_tier = DegradationTier.NORMAL
        if new_tier != DegradationTier.NORMAL and self._shed_since is None:
            self._shed_since = now
            logger.warning('Load shedding activated: p99=%.1fms tier=%s', p99, new_tier.value)
        elif new_tier == DegradationTier.NORMAL and self._shed_since is not None:
            elapsed = now - self._shed_since
            if elapsed >= self._recovery_s:
                self._shed_since = None
                logger.info('Load shedding deactivated after %.1fs recovery', elapsed)
        self._tier = new_tier
