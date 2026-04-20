from __future__ import annotations
from collections.abc import Callable
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit CSRF protection middleware.

    For every unsafe HTTP method (POST/PUT/PATCH/DELETE) that is NOT
    in the exempt paths list, the middleware:
    1. Reads the CSRF token from the request cookie.
    2. Reads the CSRF token from the request header.
    3. Validates both tokens are identical and HMAC-signed correctly.

    Exempt paths (e.g. ``/webhooks/*``) bypass the check entirely.

    Args:
        app: ASGI application to wrap.
        exempt_paths: Iterable of path prefixes to exempt from CSRF checks.
    """

    def __init__(self, app: ASGIApp, exempt_paths: list[str] | None=None) -> None:
        """Initialise the middleware with optional exempt paths.

        Args:
            app: ASGI application.
            exempt_paths: Path prefixes exempt from CSRF checking.
        """
        super().__init__(app)
        self._exempt: list[str] = exempt_paths or []

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Check CSRF token on unsafe methods; pass-through otherwise.

        Args:
            request: Incoming HTTP request.
            call_next: ASGI next middleware / route handler.

        Returns:
            Response from downstream or 403 JSON error.
        """
        if request.method not in _UNSAFE_METHODS:
            return await call_next(request)
        if self._is_exempt(request.url.path):
            return await call_next(request)
        return await self._check_csrf(request, call_next)

    def _is_exempt(self, path: str) -> bool:
        """Return True if *path* starts with any exempt prefix.

        Args:
            path: Request path string.

        Returns:
            ``True`` when path should skip CSRF validation.
        """
        return any((path.startswith(prefix) for prefix in self._exempt))

    async def _check_csrf(self, request: Request, call_next: Callable) -> Response:
        """Perform double-submit CSRF validation.

        Args:
            request: HTTP request being checked.
            call_next: Downstream handler.

        Returns:
            403 JSON error when validation fails, else downstream response.
        """
        from app.core.config import settings
        from app.security.csrf import CSRFProtection
        protection = CSRFProtection(secret_key=settings.CSRF_SECRET_KEY, cookie_name=settings.CSRF_COOKIE_NAME, header_name=settings.CSRF_HEADER_NAME)
        error = _validate_csrf_tokens(request, protection, settings)
        if error:
            return JSONResponse(status_code=403, content={'detail': error})
        return await call_next(request)
