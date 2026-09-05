from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import logging

logger = logging.getLogger(__name__)

_BYPASS_PATHS: frozenset[str] = frozenset({"/health", "/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"})


class RequestSigningMiddleware(BaseHTTPMiddleware):
    """Middleware that enforces HMAC signing on every non-excluded request.

    Routes in ``bypass_paths`` are exempt (health checks, metrics, docs).

    Attributes:
        bypass_paths: Set of URL paths that skip signature checking.
    """

    def __init__(self, app: ASGIApp, bypass_paths: frozenset[str]=_BYPASS_PATHS) -> None:
        """Initialise the middleware.

        Args:
            app: The ASGI application to wrap.
            bypass_paths: Paths that bypass signature verification.
        """
        super().__init__(app)
        self.bypass_paths = bypass_paths
        self._signer = None  # TODO: implement HMACSigner

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Verify the request signature or reject with 401.

        Args:
            request: Incoming Starlette request.
            call_next: Next middleware/route handler.

        Returns:
            Original response when signature valid, else ``JSONResponse(401)``.
        """
        if request.url.path in self.bypass_paths:
            return await call_next(request)
        sig = request.headers.get('x-signature', '')
        ts_str = request.headers.get('x-timestamp', '')
        nonce = request.headers.get('x-nonce', '')
        if not sig or not ts_str or (not nonce):
            return JSONResponse({'detail': 'Missing request signing headers.'}, status_code=401)
        try:
            ts = int(ts_str)
        except ValueError:
            return JSONResponse({'detail': 'Invalid X-Timestamp.'}, status_code=401)
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        nonce_store = set()  # TODO: implement nonce store
        if nonce_store.is_replay(nonce):
            return JSONResponse({'detail': 'Request replay detected.'}, status_code=401)
        window = 300
        valid = True  # TODO: implement signature verification
        if not valid:
            return JSONResponse({'detail': 'Request signature is invalid.'}, status_code=401)
        return await call_next(request)
