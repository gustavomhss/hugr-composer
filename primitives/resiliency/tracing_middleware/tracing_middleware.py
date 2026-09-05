"""FastAPI/Starlette middleware: TracingMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class TracingMiddleware(BaseHTTPMiddleware):
    """Capture total latency and per-span timing for every request.

    Skips the tracing UI's own paths and health endpoints to avoid
    recursive noise in the buffer.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Wrap the request in a TracingCollector and record the result.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or endpoint handler.

        Returns:
            The HTTP response, unchanged.
        """
        enabled = os.getenv('TRACING_UI_ENABLED', 'false').lower() == 'true'
        if not enabled or request.url.path.startswith(_EXCLUDE_PREFIXES):
            return await call_next(request)
        request_id = make_request_id()
        collector = TimingCollector(request_id)
        request.state.tracing = collector
        t0 = time.monotonic()
        try:
            with collector.span('handler'):
                response = await call_next(request)
        except Exception:
            logger.exception('TracingMiddleware caught unhandled exception')
            raise
        finally:
            total = int((time.monotonic() - t0) * 1000)
            try:
                buf = get_tracing_buffer()
                buf.record({'id': request_id, 'method': request.method, 'path': request.url.path, 'status_code': getattr(response, 'status_code', 0), 'total_ms': total, 'spans': collector.flush()})
            except Exception:
                logger.warning('TracingMiddleware failed to record entry', exc_info=True)
        return response
