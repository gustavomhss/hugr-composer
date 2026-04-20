from __future__ import annotations
from fastapi import Request


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Return a 429 response with Retry-After and rate-limit headers.

    Args:
        request: The request that triggered the limit.
        exc: The ``RateLimitExceeded`` raised by SlowAPI.

    Returns:
        A 429 JSONResponse with RFC 6585-compliant headers.
    """
    logger.warning('rate_limit.exceeded', extra={'path': request.url.path, 'method': request.method, 'limit': str(exc.detail)})
    retry_after = getattr(exc, 'retry_after', 60)
    return JSONResponse(status_code=429, content={'detail': 'Rate limit exceeded', 'limit': str(exc.detail), 'retry_after_seconds': retry_after}, headers={'Retry-After': str(retry_after), 'X-RateLimit-Limit': str(exc.detail)})
