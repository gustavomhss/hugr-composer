from __future__ import annotations
from collections import deque
import threading
import time


class RetryBudget:
    """Sliding-window retry budget tracker.

    Tracks total requests and retries over a rolling window.
    Blocks retries when ``retries / total > ratio``.

    Args:
        service: Logical service name (e.g. ``"stripe"``).
        ratio: Maximum allowed retry fraction (default 0.10).
        window_s: Sliding window width in seconds (default 60).
        min_requests: Minimum requests before enforcing the budget.
    """

    def __init__(self, service: str, ratio: float=0.1, window_s: float=60.0, min_requests: int=10) -> None:
        """Initialise a new retry budget for *service*.

        Args:
            service: Service name used in logs and error messages.
            ratio: Max retries / total requests before blocking.
            window_s: Sliding window width in seconds.
            min_requests: Warm-up: enforce budget only above this count.
        """
        self.service = service
        self.ratio = ratio
        self.window_s = window_s
        self.min_requests = min_requests
        self._requests: deque[float] = deque()
        self._retries: deque[float] = deque()
        self._lock = threading.Lock()

    def record_request(self) -> None:
        """Record a new inbound request for this service."""
        now = time.monotonic()
        with self._lock:
            self._requests.append(now)
            self._evict(now)

    def record_retry(self) -> None:
        """Record a retry attempt for this service."""
        now = time.monotonic()
        with self._lock:
            self._retries.append(now)
            self._evict(now)

    def can_retry(self) -> bool:
        """Return True if a retry is allowed under the current budget.

        Returns:
            ``True`` when retries are within budget or warm-up not complete.
        """
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            total = len(self._requests)
            if total < self.min_requests:
                return True
            retries = len(self._retries)
            current_ratio = retries / total if total else 0.0
            allowed = current_ratio < self.ratio
            if not allowed:
                logger.warning('Retry budget exhausted for %s: %.1f%% >= %.1f%%', self.service, current_ratio * 100, self.ratio * 100)
            return allowed

    def current_ratio(self) -> float:
        """Return the current retry ratio for observability.

        Returns:
            Float in [0.0, 1.0] representing retries / total requests.
        """
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            total = len(self._requests)
            retries = len(self._retries)
            return retries / total if total > 0 else 0.0

    def stats(self) -> dict:
        """Return current budget statistics dict.

        Returns:
            Dict with keys: service, total_requests, total_retries,
            current_ratio, budget_ratio, budget_exhausted.
        """
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            total = len(self._requests)
            retries = len(self._retries)
        ratio = retries / total if total > 0 else 0.0
        return {'service': self.service, 'total_requests': total, 'total_retries': retries, 'current_ratio': round(ratio, 4), 'budget_ratio': self.ratio, 'budget_exhausted': ratio >= self.ratio and total >= self.min_requests}

    def _evict(self, now: float) -> None:
        """Remove entries outside the sliding window (call with lock held).

        Args:
            now: Current monotonic time.
        """
        cutoff = now - self.window_s
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()
        while self._retries and self._retries[0] < cutoff:
            self._retries.popleft()
