"""FastAPI/Starlette middleware: AnomalyMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable
import time
import asyncio

from ..anomaly_detector import AnomalyDetector

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


_detector: AnomalyDetector | None = None


def get_detector() -> AnomalyDetector | None:
    """Return the global anomaly detector instance."""
    return _detector


def init_detector(sensitivity: float = 3.0, window_size: int = 100, webhook_url: str | None = None) -> AnomalyDetector:
    """Initialize the global anomaly detector."""
    global _detector
    _detector = AnomalyDetector(sensitivity=sensitivity, window_size=window_size, alert_webhook_url=webhook_url)
    return _detector


class AnomalyMiddleware(BaseHTTPMiddleware):
    """Observe every request/response and trigger alerts on anomaly.

    Args:
        app: ASGI application.
        webhook_url: Optional webhook URL for alert dispatch.
        sensitivity: Z-score threshold (default 3.0).
        window_size: Samples per sliding window (default 100).
    """

    def __init__(
        self,
        app: ASGIApp,
        webhook_url: str | None = None,
        sensitivity: float = 3.0,
        window_size: int = 100,
    ) -> None:
        super().__init__(app)
        init_detector(sensitivity=sensitivity, window_size=window_size, webhook_url=webhook_url)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """Time request, observe metrics, fire alerts on anomaly."""
        detector = get_detector()
        if detector is None:
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        content_length = int(response.headers.get("content-length", 0))
        anomalies = detector.observe(
            status_code=response.status_code,
            duration_ms=duration_ms,
            payload_bytes=content_length,
        )
        if anomalies:
            for anom in anomalies:
                asyncio.create_task(log_anomaly(anom))
        return response


async def log_anomaly(anom: dict) -> None:
    """Log anomaly and optionally dispatch to webhook."""
    import logging
    logger = logging.getLogger(__name__)
    logger.warning("Anomaly detected: %s", anom)
