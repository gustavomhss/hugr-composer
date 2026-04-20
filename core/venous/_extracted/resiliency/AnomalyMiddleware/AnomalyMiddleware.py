from __future__ import annotations
from collections.abc import Callable
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
import asyncio
import time


class AnomalyMiddleware(BaseHTTPMiddleware):
    """Observe every request/response and trigger alerts on anomaly.

    Args:
        app: ASGI application.
        webhook_url: Optional webhook URL for alert dispatch.
    """

    def __init__(self, app: Callable, webhook_url: str | None=None) -> None:
        super().__init__(app)
        self._dispatcher = AlertDispatcher(webhook_url=webhook_url)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Time request, observe metrics, fire alerts on anomaly."""
        detector = get_detector()
        if detector is None:
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000
        content_length = int(response.headers.get('content-length', 0))
        anomalies = detector.observe(status_code=response.status_code, duration_ms=duration_ms, payload_bytes=content_length)
        if anomalies:
            for anom in anomalies:
                asyncio.ensure_future(self._dispatcher.dispatch(anom))
        return response
