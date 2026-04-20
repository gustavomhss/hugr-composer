from __future__ import annotations
from fastapi import Request
from fastapi import Response
from starlette.middleware.base import BaseHTTPMiddleware


class LeakDetectorMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that scans responses for secret leaks.

    Add to ``app/main.py``::

        from app.middleware.leak_detector import LeakDetectorMiddleware
        app.add_middleware(LeakDetectorMiddleware)
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process the request and scan the response for leaks.

        Args:
            request: Incoming HTTP request.
            call_next: Next middleware or route handler.

        Returns:
            The response, with any secret substrings replaced.
        """
        response = await call_next(request)
        content_type = response.headers.get('content-type', '')
        if 'application/json' not in content_type and 'text/' not in content_type:
            return response
        return await self._scan_response(response, request)

    async def _scan_response(self, response: Response, request: Request) -> Response:
        """Read, scan, and optionally sanitise a text response.

        Args:
            response: Original response from the route handler.
            request: Original request (for logging context).

        Returns:
            Sanitised response with leaks replaced.
        """
        from starlette.responses import Response as BaseResponse
        body = b''
        async for chunk in response.body_iterator:
            body += chunk if isinstance(chunk, bytes) else chunk.encode()
        text = body.decode('utf-8', errors='replace')
        secrets = _collect_secret_values()
        found: list[str] = []
        for secret in secrets:
            if secret and len(secret) > 4 and (secret in text):
                text = text.replace(secret, '[REDACTED]')
                found.append(secret[:4] + '***')
        if found:
            logger.warning('secret_leak_detected', extra={'path': str(request.url.path), 'fragments': found})
        return BaseResponse(content=text.encode(), status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)
