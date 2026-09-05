"""Pure Python primitive: RequestMetrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class RequestMetrics:
    """Prometheus RED metrics: request_total, duration_seconds, errors_total.

    All prometheus_client objects are created lazily on first use.

    Args:
        prefix: Metric name prefix (e.g. ``"http"``).
    """

    def __init__(self, prefix: str='http') -> None:
        """Initialise metric names; prometheus_client objects built lazily."""
        self._prefix = prefix
        self._counter: Any = None
        self._histogram: Any = None
        self._errors: Any = None

    def _ensure_initialized(self) -> None:
        """Create prometheus_client objects on first call (lazy import)."""
        if self._counter is not None:
            return
        import prometheus_client as prom
        p = self._prefix
        buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)
        self._counter = prom.Counter(f'{p}_requests_total', 'Total HTTP requests', ['method', 'path', 'status'])
        self._histogram = prom.Histogram(f'{p}_request_duration_seconds', 'HTTP request latency', ['method', 'path'], buckets=buckets)
        self._errors = prom.Counter(f'{p}_request_errors_total', 'Total HTTP errors (4xx + 5xx)', ['method', 'path', 'status'])

    def record_request(self, method: str, path: str, status: int, duration: float) -> None:
        """Record one HTTP request.

        Args:
            method: HTTP method (GET, POST, …).
            path: URL path (normalised, no query string).
            status: HTTP response status code.
            duration: Request duration in seconds.
        """
        try:
            self._ensure_initialized()
            labels = [method, path, str(status)]
            self._counter.labels(*labels).inc()
            self._histogram.labels(method, path).observe(duration)
            if status >= 400:
                self._errors.labels(*labels).inc()
        except Exception:
            logger.warning('Failed to record Prometheus metric', exc_info=True)
