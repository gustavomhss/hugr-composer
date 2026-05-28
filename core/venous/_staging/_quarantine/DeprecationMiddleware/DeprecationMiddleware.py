from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class DeprecationMiddleware(BaseHTTPMiddleware):
    """Add RFC 8594 Sunset/Deprecation headers to deprecated endpoint responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Intercept response and add deprecation headers when applicable.

        Args:
            request: Incoming HTTP request.
            call_next: ASGI call-next handler.

        Returns:
            Response with Sunset/Deprecation/Link headers if deprecated.
        """
        response = await call_next(request)
        entry = registry.get(request.url.path, request.method)
        if entry is not None:
            response.headers['Sunset'] = entry.sunset_header
            response.headers['Deprecation'] = 'true'
            if entry.replacement:
                response.headers['Link'] = f'<{entry.replacement}>; rel="successor-version"'
            reporter.record(request.url.path, request.method)
        return response
