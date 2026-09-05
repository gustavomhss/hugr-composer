from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_BYPASS_PATHS: frozenset[str] = frozenset({"/health", "/healthz", "/readyz", "/metrics", "/docs", "/openapi.json"})

class DLPMiddleware(BaseHTTPMiddleware):
    """Response middleware that detects and redacts PII/PHI/PCI in JSON.

    Attributes:
        bypass_paths: URL paths that skip DLP scanning.
    """

    def __init__(self, app: ASGIApp, bypass_paths: frozenset[str]=_BYPASS_PATHS) -> None:
        """Initialise the middleware.

        Args:
            app: ASGI application to wrap.
            bypass_paths: Paths that skip DLP scanning.
        """
        super().__init__(app)
        self.bypass_paths = bypass_paths

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Intercept the response and apply DLP redaction.

        Args:
            request: Incoming Starlette request.
            call_next: Next handler.

        Returns:
            Original or DLP-redacted response.
        """
        if not getattr(settings, 'DLP_ENABLED', True):
            return await call_next(request)
        if request.url.path in self.bypass_paths:
            return await call_next(request)
        response: Response = await call_next(request)
        content_type = response.headers.get('content-type', '')
        is_json = any((ct in content_type for ct in _JSON_CONTENT_TYPES))
        if not is_json:
            return response
        body = b''
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()
        mode = getattr(settings, 'DLP_REDACTION_MODE', 'full')
        redactor = Redactor(mode=mode)
        redacted_body = redactor.redact_json_bytes(body)
        headers = dict(response.headers)
        headers['content-length'] = str(len(redacted_body))
        return Response(content=redacted_body, status_code=response.status_code, headers=headers, media_type='application/json')
