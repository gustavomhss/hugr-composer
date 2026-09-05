"""Statistical anomaly detector for HTTP request metrics."""

from __future__ import annotations
import time
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


class _MetricWindow:
    """Sliding window for computing z-scores on a metric stream."""

    def __init__(self, window_size: int):
        self.window_size = window_size
        self.samples: deque[float] = deque(maxlen=window_size)
        self._sum = 0.0
        self._sum_sq = 0.0

    def observe(self, value: float) -> None:
        if len(self.samples) == self.window_size:
            old = self.samples.popleft()
            self._sum -= old
            self._sum_sq -= old * old
        self.samples.append(value)
        self._sum += value
        self._sum_sq += value * value

    def z_score(self, value: float) -> float | None:
        if len(self.samples) < 2:
            return None
        mean = self._sum / len(self.samples)
        var = (self._sum_sq / len(self.samples)) - (mean * mean)
        if var <= 0:
            return 0.0
        std = var ** 0.5
        return (value - mean) / std

    def baseline(self) -> dict:
        if not self.samples:
            return {'mean': 0.0, 'std': 0.0, 'count': 0}
        mean = self._sum / len(self.samples)
        var = (self._sum_sq / len(self.samples)) - (mean * mean)
        std = max(var, 0) ** 0.5
        return {'mean': mean, 'std': std, 'count': len(self.samples)}


class AnomalyDetector:
    """Statistical anomaly detector for HTTP request metrics.

    Tracks four metrics per endpoint: request rate (req/s), error rate
    (fraction of 5xx), p99 latency (ms), and payload size (bytes).

    Args:
        sensitivity: Z-score threshold to trigger an alert (default 3.0).
        window_size: Number of samples per sliding window.
        alert_webhook_url: Optional webhook URL for alerts.
    """

    def __init__(self, sensitivity: float = 3.0, window_size: int = 100, alert_webhook_url: str | None = None) -> None:
        self.sensitivity = sensitivity
        self.window_size = window_size
        self.alert_webhook_url = alert_webhook_url
        self._request_rate = _MetricWindow(window_size)
        self._error_rate = _MetricWindow(window_size)
        self._latency = _MetricWindow(window_size)
        self._payload_size = _MetricWindow(window_size)
        self._anomalies: list[dict] = []
        self._last_request_ts: float = time.monotonic()

    def observe(self, status_code: int, duration_ms: float, payload_bytes: int) -> list[dict]:
        """Observe a completed request and return any anomalies detected.

        Args:
            status_code: HTTP response status code.
            duration_ms: Request duration in milliseconds.
            payload_bytes: Response body size in bytes.

        Returns:
            List of anomaly dicts (empty when no anomaly).
        """
        now = time.monotonic()
        elapsed = max(now - self._last_request_ts, 0.001)
        self._last_request_ts = now
        req_rate = 1.0 / elapsed
        err_flag = 1.0 if status_code >= 500 else 0.0
        anomalies: list[dict] = []
        metrics = {
            'request_rate': (self._request_rate, req_rate),
            'error_rate': (self._error_rate, err_flag),
            'latency_ms': (self._latency, duration_ms),
            'payload_bytes': (self._payload_size, float(payload_bytes)),
        }
        for name, (window, value) in metrics.items():
            z = window.z_score(value)
            window.observe(value)
            if z is not None and abs(z) > self.sensitivity:
                anom = {'metric': name, 'value': value, 'z_score': round(z, 2), 'ts': time.time()}
                anomalies.append(anom)
                self._anomalies.append(anom)
                if len(self._anomalies) > 1000:
                    self._anomalies = self._anomalies[-500:]
        return anomalies

    def status(self) -> dict:
        """Return current baselines and recent anomaly count."""
        return {
            'sensitivity': self.sensitivity,
            'window_size': self.window_size,
            'baselines': {
                'request_rate': self._request_rate.baseline(),
                'error_rate': self._error_rate.baseline(),
                'latency_ms': self._latency.baseline(),
                'payload_bytes': self._payload_size.baseline(),
            },
            'recent_anomalies': self._anomalies[-20:],
            'total_anomalies': len(self._anomalies),
        }
