from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class ShutdownMiddleware(BaseHTTPMiddleware):
    """Reject new inbound requests during shutdown drain phase.

    In-flight requests (already past this middleware) are unaffected.
    The load balancer is expected to stop routing after seeing
    ``/healthz → 503`` from the ShutdownHealthGate.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Reject new requests during drain; track in-flight count.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            503 response during drain, or the downstream response.
        """
        sd = get_graceful_shutdown()
        if sd.is_draining() and request.url.path not in _PASS_THROUGH_PATHS:
            logger.debug('Rejecting new request during drain: %s %s', request.method, request.url.path)
            return JSONResponse(status_code=503, content={'detail': 'Service is shutting down — please retry.'}, headers={'Retry-After': '10'})
        sd.increment_in_flight()
        try:
            return await call_next(request)
        finally:
            sd.decrement_in_flight()
