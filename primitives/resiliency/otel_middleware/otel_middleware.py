"""FastAPI/Starlette middleware: OtelMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class OTELMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that creates an OTEL span for each HTTP request.

    When ``OTEL_ENABLED`` is ``False`` the middleware delegates to
    ``call_next`` immediately with no telemetry overhead.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Wrap the request in an OTEL span when tracing is enabled.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            HTTP response with span attributes set.
        """
        from app.core.config import settings
        if not settings.OTEL_ENABLED:
            return await call_next(request)
        return await self._traced_dispatch(request, call_next)

    async def _traced_dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Execute the request inside an active OTEL span.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            HTTP response; span is ended whether or not an exception occurs.
        """
        from app.telemetry.setup import get_tracer
        tracer = get_tracer('app.middleware')
        span_name = f'{request.method} {request.url.path}'
        t0 = time.monotonic()
        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute('http.method', request.method)
            span.set_attribute('http.url', str(request.url))
            span.set_attribute('http.route', request.url.path)
            response = await call_next(request)
            elapsed = int((time.monotonic() - t0) * 1000)
            span.set_attribute('http.status_code', response.status_code)
            span.set_attribute('http.response_time_ms', elapsed)
            return response
