from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class BulkheadMiddleware(BaseHTTPMiddleware):
    """Middleware that isolates endpoint groups with separate semaphore pools."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request through the appropriate bulkhead pool.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            503 with detail if pool is full, else upstream response.
        """
        if not _is_enabled():
            return await call_next(request)
        group = classify_route(request.url.path)
        bulkhead = get_bulkhead()
        try:
            async with bulkhead.acquire(group):
                return await call_next(request)
        except BulkheadFullError as exc:
            logger.warning("Bulkhead full for group '%s': %d/%d", group, exc.current, exc.maximum)
            return JSONResponse(status_code=503, content={'detail': f"Service unavailable: '{group}' pool at capacity. Please retry."}, headers={'X-Bulkhead-Group': group})
