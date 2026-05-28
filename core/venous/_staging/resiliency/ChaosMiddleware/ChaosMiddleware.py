from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class ChaosMiddleware(BaseHTTPMiddleware):
    """Apply chaos fault injection to incoming requests.

    Only active when chaos engine reports ``is_enabled() == True``.
    Never active in production (hardcoded guard in ChaosEngine).

    Args:
        app: ASGI application to wrap.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Apply chaos faults then forward the request.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware / route handler.

        Returns:
            Response from downstream, possibly after injected faults.
        """
        engine = get_chaos_engine()
        if not engine.is_enabled():
            return await call_next(request)
        path = request.url.path
        if path in ('/healthz', '/chaos/status', '/chaos/enable', '/chaos/disable'):
            return await call_next(request)
        latency_inj = LatencyInjector(latency_ms=engine.latency_ms)
        error_inj = ErrorInjector(error_rate=engine.error_rate)
        timeout_inj = TimeoutInjector(timeout_rate=engine.timeout_rate)
        await latency_inj.inject()
        error_inj.inject()
        await timeout_inj.inject()
        return await call_next(request)
