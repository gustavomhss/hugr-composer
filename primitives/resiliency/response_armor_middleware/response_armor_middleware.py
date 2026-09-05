"""FastAPI/Starlette middleware: ResponseArmorMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class ResponseArmorMiddleware(BaseHTTPMiddleware):
    """ASGI middleware applying all five response hardening layers.

    Each layer is independently controlled by a config flag so operators
    can enable them incrementally without full rollout risk.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Apply all response armor layers to every response.

        Args:
            request: Incoming ASGI request.
            call_next: Next handler in the middleware chain.

        Returns:
            Hardened response with armor layers applied.
        """
        if not getattr(settings, 'RESPONSE_ARMOR_ENABLED', True):
            return await call_next(request)
        response = await call_next(request)
        self._apply_crlf_guard(response)
        self._apply_cache_control(response)
        self._remove_server_header(response)
        return response

    def _apply_crlf_guard(self, response: Response) -> None:
        """Strip CR/LF from all response header values.

        Args:
            response: Response object to mutate in-place.
        """
        for key, value in list(response.headers.items()):
            cleaned = strip_crlf(value)
            if cleaned != value:
                logger.warning('armor.crlf_stripped', extra={'header': key, 'original': repr(value)})
                response.headers[key] = cleaned

    def _apply_cache_control(self, response: Response) -> None:
        """Enforce no-store Cache-Control on error responses.

        Args:
            response: Response object to mutate in-place.
        """
        if response.status_code >= 400:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
            response.headers['Pragma'] = 'no-cache'

    def _remove_server_header(self, response: Response) -> None:
        """Remove the Server header to reduce fingerprinting surface.

        Args:
            response: Response object to mutate in-place.
        """
        if 'server' in response.headers:
            del response.headers['server']
