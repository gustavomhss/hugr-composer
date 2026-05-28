from __future__ import annotations
from starlette.types import ASGIApp
import os


class CORSConfigMiddleware:
    """ASGI wrapper that installs CORSMiddleware from env-var settings.

    Reads ``CORS_ALLOWED_ORIGINS``, ``CORS_ALLOW_CREDENTIALS``, and
    ``CORS_MAX_AGE`` from environment variables, then wraps the inner
    app with FastAPI's built-in ``CORSMiddleware``.

    Args:
        app: The inner ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Configure CORS from environment and wrap the app."""
        raw_origins = os.getenv('CORS_ALLOWED_ORIGINS', '*')
        origins = _parse_origins(raw_origins)
        environment = os.getenv('ENVIRONMENT', 'local')
        allow_credentials = os.getenv('CORS_ALLOW_CREDENTIALS', 'false').lower() == 'true'
        max_age = int(os.getenv('CORS_MAX_AGE', '600'))
        _warn_if_wildcard(origins, environment)
        self._app = CORSMiddleware(app=app, allow_origins=origins, allow_credentials=allow_credentials, allow_methods=['*'], allow_headers=['*'], max_age=max_age)

    async def __call__(self, scope, receive, send) -> None:
        """Delegate every ASGI call to the wrapped CORSMiddleware."""
        await self._app(scope, receive, send)
