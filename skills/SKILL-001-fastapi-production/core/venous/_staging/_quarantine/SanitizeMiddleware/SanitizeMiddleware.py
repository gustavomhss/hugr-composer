from __future__ import annotations
from collections.abc import Callable
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import json


class SanitizeMiddleware(BaseHTTPMiddleware):
    """Middleware that sanitizes JSON request body string fields.

    Recursively walks the parsed JSON body up to ``max_depth`` levels
    and sanitizes all string values using ``InputSanitizer.sanitize_html()``.
    Non-JSON bodies are passed through unmodified.

    Args:
        app: ASGI application.
        max_depth: Maximum recursion depth for nested JSON objects.
    """

    def __init__(self, app: ASGIApp, max_depth: int=5) -> None:
        """Initialise the middleware with a configurable depth limit.

        Args:
            app: ASGI application to wrap.
            max_depth: Maximum nesting depth to sanitize (default 5).
        """
        super().__init__(app)
        self._max_depth = max_depth

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Sanitize JSON body for unsafe methods; pass-through otherwise.

        Args:
            request: Incoming HTTP request.
            call_next: Downstream handler.

        Returns:
            Response from downstream handler.
        """
        if request.method not in _SANITIZE_METHODS:
            return await call_next(request)
        content_type = request.headers.get('content-type', '')
        if 'application/json' not in content_type:
            return await call_next(request)
        return await self._sanitize_body(request, call_next)

    async def _sanitize_body(self, request: Request, call_next: Callable) -> Response:
        """Parse, sanitize and reconstruct the JSON request body.

        Args:
            request: HTTP request with a JSON body.
            call_next: Downstream handler.

        Returns:
            Response from downstream, or 400 on JSON parse failure.
        """
        from app.security.sanitizer import InputSanitizer
        try:
            raw = await request.body()
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return await call_next(request)
        sanitizer = InputSanitizer()
        cleaned = _sanitize_value(body, sanitizer, depth=0, max_depth=self._max_depth)
        cleaned_bytes = json.dumps(cleaned).encode()
        request._body = cleaned_bytes
        return await call_next(request)
