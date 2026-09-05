"""FastAPI/Starlette middleware: OpaMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class OPAMiddleware(BaseHTTPMiddleware):
    """Request-level OPA enforcement middleware.

    Queries OPA for every request not in ``_SKIP_PREFIXES``.  Returns
    HTTP 403 when OPA denies access.  If OPA is unreachable, the
    circuit-breaker / fail-open policy in OPAClient controls the outcome.
    """

    async def dispatch(self, request: Request, call_next):
        """Intercept request, query OPA, and deny or pass through.

        Args:
            request: Incoming HTTP request.
            call_next: ASGI callable for the next handler.

        Returns:
            HTTP 403 JSON response on denial, or the downstream response.
        """
        path = request.url.path
        if any((path.startswith(pfx) for pfx in _SKIP_PREFIXES)):
            return await call_next(request)
        subject = request.headers.get('X-User-Id', 'anonymous')
        opa_input = OPAInput(subject=subject, action=request.method, resource=path, context={'query': str(request.query_params)})
        client = get_opa_client()
        decision = await client.query(opa_input)
        if not decision.allow:
            logger.warning('OPA denied subject=%s action=%s resource=%s reason=%s', subject, request.method, path, decision.reason)
            return JSONResponse(status_code=403, content={'detail': 'Forbidden by policy'})
        return await call_next(request)
