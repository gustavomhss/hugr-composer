from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


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
        self._signer = HMACSigner(settings.REQUEST_SIGNING_SECRET)

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
        nonce_store = get_nonce_store()
        if nonce_store.is_replay(nonce):
            return JSONResponse({'detail': 'Request replay detected.'}, status_code=401)
        window = getattr(settings, 'REQUEST_SIGNING_TIMESTAMP_WINDOW_S', 300)
        valid = self._signer.verify(method=request.method, path=request.url.path, query=request.url.query or '', headers=headers, body=body, signature=sig, timestamp=ts, nonce=nonce, window_seconds=window)
        if not valid:
            return JSONResponse({'detail': 'Request signature is invalid.'}, status_code=401)
        return await call_next(request)
