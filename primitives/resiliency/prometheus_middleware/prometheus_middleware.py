"""FastAPI/Starlette middleware: PrometheusMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that records RED metrics for each request.

    Skips the ``/metrics`` endpoint itself to avoid self-instrumentation.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Record timing and status for every request.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            HTTP response, after recording metrics.
        """
        if request.url.path == '/metrics':
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start
        metrics = get_metrics()
        if metrics is not None:
            metrics.record_request(method=request.method, path=request.url.path, status=response.status_code, duration=duration)
        return response
