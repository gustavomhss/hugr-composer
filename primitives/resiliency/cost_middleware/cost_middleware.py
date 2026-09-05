"""FastAPI/Starlette middleware: CostMiddleware."""

from __future__ import annotations
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class CostMiddleware(BaseHTTPMiddleware):
    """Annotate each response with X-Request-Cost-Estimate header.

    The header value is a USD string like ``$0.000042``. If cost
    tracking is disabled or the estimator raises, the header is omitted.
    """

    def __init__(self, app: Any, enabled: bool=True) -> None:
        """Initialise middleware."""
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request, estimate cost, annotate response header."""
        if not self._enabled:
            return await call_next(request)
        path = request.url.path
        if any((path.startswith(p) for p in _SKIP_PATHS)):
            return await call_next(request)
        t0 = time.monotonic()
        request_id = str(uuid.uuid4())
        from app.costs.tracker import RequestContext
        ctx = RequestContext(request_id=request_id, path=path, method=request.method)
        request.state.cost_context = ctx
        response = await call_next(request)
        ctx.duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            from app.costs.tracker import get_cost_tracker
            tracker = get_cost_tracker()
            estimate = tracker.estimate_request(ctx)
            response.headers['X-Request-Cost-Estimate'] = estimate.as_header_value()
            response.headers['X-Request-Id'] = request_id
        except Exception as exc:
            logger.debug('Cost estimation failed (non-fatal): %s', exc)
        return response
