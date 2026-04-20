from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
import json


class CedarAuthzMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that enforces Cedar policies on every request.

    Attributes:
        skip_paths: Set of URL paths that bypass Cedar evaluation.
    """

    def __init__(self, app, skip_paths: frozenset[str] | None=None) -> None:
        """Initialise the middleware.

        Args:
            app: The ASGI application to wrap.
            skip_paths: URL paths that skip Cedar evaluation.  Defaults to
                health-check and documentation paths.
        """
        super().__init__(app)
        self.skip_paths = skip_paths if skip_paths is not None else _DEFAULT_SKIP

    async def dispatch(self, request: Request, call_next) -> Response:
        """Evaluate Cedar policy before passing the request downstream.

        Args:
            request: Incoming Starlette request.
            call_next: Next middleware or route handler.

        Returns:
            HTTP 403 JSON response on Cedar deny; otherwise the downstream
            response.
        """
        from app.core.config import settings
        if not getattr(settings, 'CEDAR_ENABLED', False):
            return await call_next(request)
        if request.url.path in self.skip_paths:
            return await call_next(request)
        principal = self._extract_principal(request)
        action = f'Action::"{request.method.lower()}"'
        resource = f'Resource::"{request.url.path}"'
        from app.authz.engine import get_cedar_engine
        allowed = get_cedar_engine().is_authorized(principal, action, resource)
        if not allowed:
            logger.warning('Cedar DENY principal=%s action=%s resource=%s', principal, action, resource)
            body = json.dumps({'detail': 'Forbidden by Cedar policy'})
            return Response(content=body, status_code=403, media_type='application/json')
        return await call_next(request)

    @staticmethod
    def _extract_principal(request: Request) -> str:
        """Extract a Cedar principal string from the request.

        Uses the JWT ``sub`` claim when available; falls back to
        ``'User::anonymous'`` for unauthenticated requests.

        Args:
            request: Incoming Starlette request.

        Returns:
            Cedar principal entity string.
        """
        user = getattr(request.state, 'user', None)
        if user and hasattr(user, 'id'):
            return f'User::"{user.id}"'
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return 'User::"jwt-user"'
        return 'User::"anonymous"'
