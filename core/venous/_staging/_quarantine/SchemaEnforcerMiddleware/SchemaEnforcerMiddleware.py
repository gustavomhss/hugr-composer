from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class SchemaEnforcerMiddleware(BaseHTTPMiddleware):
    """ASGI middleware that enforces OpenAPI schema compliance.

    On startup loads the spec once and caches ``spec_routes``.
    In enforce mode, returns 403 for shadow routes when
    SCHEMA_ENFORCER_BLOCK_SHADOW is True.
    """

    def __init__(self, app: FastAPI, **kwargs: object) -> None:
        """Initialise middleware, loading spec from disk.

        Args:
            app: The FastAPI/Starlette application.
            **kwargs: Forwarded to BaseHTTPMiddleware.
        """
        super().__init__(app, **kwargs)
        self._spec = load_spec()
        self._spec_routes = extract_route_paths(self._spec)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Enforce schema rules on the incoming request.

        Args:
            request: Incoming ASGI request.
            call_next: Next middleware/route handler.

        Returns:
            Response from downstream, or 403/422 on schema violation.
        """
        mode = getattr(settings, 'SCHEMA_ENFORCER_MODE', 'detect')
        block_shadow = getattr(settings, 'SCHEMA_ENFORCER_BLOCK_SHADOW', False)
        path = request.url.path
        shadow = detect_shadow_routes([path], self._spec_routes)
        if shadow:
            logger.warning('schema_enforcer.shadow_route', extra={'path': path, 'mode': mode})
            if mode == 'enforce' and block_shadow:
                return JSONResponse(status_code=403, content={'detail': f'Undocumented endpoint: {path}'})
        return await call_next(request)
