"""FastAPI/Starlette middleware: VersionResolverMiddleware."""

from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from typing import Callable, Awaitable

RequestResponseEndpoint = Callable[[Request], Awaitable[Response]]


class VersionResolverMiddleware(BaseHTTPMiddleware):
    """Resolve API version from URL path and annotate the request/response.

    For unknown versions the middleware returns a 400 JSON error.
    For deprecated versions it attaches Deprecation/Sunset/Link headers.

    Args:
        app: The ASGI application to wrap.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        """Intercept every request to resolve and validate the API version.

        Args:
            request: Incoming HTTP request.
            call_next: Next ASGI handler.

        Returns:
            HTTP response, possibly with versioning headers injected.
        """
        version = extract_version_from_path(request.url.path)
        if version is None:
            version = _DEFAULT_VERSION
        if version not in registry.supported():
            return Response(content='{"detail": "Unsupported API version: ' + version + '"}', status_code=400, media_type='application/json')
        request.state.api_version = version
        response: Response = await call_next(request)
        response.headers['X-API-Version'] = version
        info = registry.get(version)
        if info and info.is_deprecated:
            response.headers['Deprecation'] = 'true'
            if info.sunset_header:
                response.headers['Sunset'] = info.sunset_header
            next_ver = _next_version(version)
            if next_ver:
                successor = request.url.path.replace(f'/api/{version}', f'/api/{next_ver}', 1)
                response.headers['Link'] = f'<{successor}>; rel="successor-version"'
        return response
