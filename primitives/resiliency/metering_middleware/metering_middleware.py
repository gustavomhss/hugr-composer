"""FastAPI/Starlette middleware: MeteringMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class MeteringMiddleware(BaseHTTPMiddleware):
    """ASGI middleware: records API usage events and enforces quotas.

    Quota enforcement is opt-in — when a tenant_id is found in the
    quota cache AND METERING_ENABLED is True, a 429 is returned
    when their monthly limit is exceeded.
    """

    def __init__(self, app: Any, enabled: bool=True) -> None:
        """Initialise middleware."""
        super().__init__(app)
        self._enabled = enabled

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Record usage event; enforce quota before forwarding."""
        if not self._enabled or not _is_metered_path(request.url.path):
            return await call_next(request)
        tenant_id = _extract_tenant_id(request)
        quota = _quota_cache.get(tenant_id)
        if quota and quota.current_usage >= quota.monthly_limit:
            return JSONResponse(status_code=429, content={'detail': 'Monthly API quota exhausted. Upgrade your plan.'}, headers={'Retry-After': '86400'})
        t0 = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - t0) * 1000)
        event = MeterEvent(tenant_id=tenant_id, endpoint=request.url.path, method=request.method, status_code=response.status_code, duration_ms=duration_ms, response_bytes=int(response.headers.get('content-length', 0)), timestamp=time.time())
        _event_buffer.add(event)
        if quota:
            quota.current_usage += 1
            _check_usage_alerts(tenant_id, quota)
        return response
