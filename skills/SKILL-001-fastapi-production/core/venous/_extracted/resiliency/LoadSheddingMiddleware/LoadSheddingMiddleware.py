from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
import time


class LoadSheddingMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces load shedding based on p99 latency."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request, shed load if necessary.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            HTTP response (429 if shed, else upstream response).
        """
        if not _is_enabled():
            return await call_next(request)
        priority = classify_request(request.url.path, request.method)
        shedder = get_load_shedder()
        if shedder.is_shedding() and priority == RequestPriority.LOW:
            logger.debug('Shedding LOW priority request: %s %s', request.method, request.url.path)
            return JSONResponse(status_code=429, content={'detail': 'Service under load — low priority request shed.'}, headers={'Retry-After': str(_RETRY_AFTER_SECONDS)})
        start = time.monotonic()
        response = await call_next(request)
        latency_ms = (time.monotonic() - start) * 1000.0
        shedder.record_latency(latency_ms)
        manager = get_degradation_manager()
        manager.set_tier(shedder.get_tier())
        return response
