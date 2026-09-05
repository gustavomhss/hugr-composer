from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class UploadSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit.

    Attributes:
        max_size: Maximum allowed ``Content-Length`` in bytes.
    """

    def __init__(self, app: ASGIApp, max_size: int | None=None) -> None:
        """Initialise the middleware.

        Args:
            app: The ASGI application to wrap.
            max_size: Override maximum bytes. Defaults to
                ``settings.S3_MAX_UPLOAD_SIZE_BYTES``.
        """
        super().__init__(app)
        self.max_size = max_size if max_size is not None else settings.S3_MAX_UPLOAD_SIZE_BYTES

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Intercept the request and reject oversized uploads.

        Args:
            request: Incoming HTTP request.
            call_next: Next ASGI handler in the chain.

        Returns:
            HTTP 413 if Content-Length exceeds limit, else the downstream
            response.
        """
        if request.method in ('PUT', 'POST'):
            content_length_str = request.headers.get('content-length')
            if content_length_str is not None:
                try:
                    content_length = int(content_length_str)
                except ValueError:
                    content_length = 0
                if content_length > self.max_size:
                    return Response(content=f'Upload exceeds maximum size of {self.max_size} bytes.', status_code=413)
        return await call_next(request)
