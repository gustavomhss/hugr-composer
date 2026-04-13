"""Generator for an Idempotency-Key middleware backed by Redis.

Clients set an ``Idempotency-Key`` header on mutating requests
(POST/PUT/PATCH/DELETE).  The middleware caches the first response
for ``(method, path, key)`` in Redis for 24h and returns the cached
response on subsequent attempts, so retries are safe.
"""

from __future__ import annotations

import textwrap
from pathlib import Path


def generate_idempotency_middleware(
    output_dir: str,
    ttl_seconds: int = 60 * 60 * 24,
) -> dict:
    """Generate ``middleware/idempotency.py`` with ``IdempotencyMiddleware``.

    Args:
        output_dir: The app package directory (``out/app``).
        ttl_seconds: TTL of cached responses.  Defaults to 24 hours.

    Returns:
        Dict with ``files_created`` and ``notes``.
    """
    out = Path(output_dir) / "middleware"
    out.mkdir(parents=True, exist_ok=True)

    content = textwrap.dedent(f'''\
        """Idempotency-Key middleware.

        Honours the ``Idempotency-Key`` header on mutating requests so
        retries do not cause duplicate side-effects.  The first response
        for a given ``(method, path, key)`` is stored in Redis for 24h
        and returned verbatim for subsequent matches.

        Requires Redis — if Redis is unavailable, requests pass through
        unchanged (fail-open) so the API keeps working, but a warning
        is logged.
        """

        from __future__ import annotations

        import hashlib
        import json
        import logging

        from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
        from starlette.requests import Request
        from starlette.responses import JSONResponse, Response

        from app.core.config import settings

        _log = logging.getLogger(__name__)

        _IDEMPOTENCY_TTL = {ttl_seconds}
        _MUTATING_METHODS = {{"POST", "PUT", "PATCH", "DELETE"}}


        class IdempotencyMiddleware(BaseHTTPMiddleware):
            """Cache responses by ``Idempotency-Key`` header."""

            async def dispatch(
                self,
                request: Request,
                call_next: RequestResponseEndpoint,
            ) -> Response:
                if request.method not in _MUTATING_METHODS:
                    return await call_next(request)

                key = request.headers.get("idempotency-key")
                if not key:
                    return await call_next(request)

                cache_key = _cache_key(request.method, request.url.path, key)

                redis = await _get_redis()
                if redis is None:
                    return await call_next(request)

                try:
                    cached = await redis.get(cache_key)
                    if cached is not None:
                        try:
                            payload = json.loads(cached)
                            return JSONResponse(
                                status_code=payload["status"],
                                content=payload["body"],
                                headers=payload.get("headers", {{}}),
                            )
                        except (json.JSONDecodeError, KeyError):
                            _log.warning(
                                "idempotency_cache_corrupt", extra={{"key": cache_key}}
                            )

                    response = await call_next(request)

                    # Only cache successful / client-error responses
                    # (2xx, 4xx).  Avoid caching 5xx so transient server
                    # failures can be retried normally.
                    if 200 <= response.status_code < 500:
                        body_bytes = b""
                        async for chunk in response.body_iterator:
                            body_bytes += chunk

                        try:
                            body_json = json.loads(body_bytes) if body_bytes else None
                        except json.JSONDecodeError:
                            body_json = None

                        if body_json is not None:
                            payload = {{
                                "status": response.status_code,
                                "body": body_json,
                                "headers": {{
                                    k: v
                                    for k, v in response.headers.items()
                                    if k.lower() in {{"content-type"}}
                                }},
                            }}
                            await redis.set(
                                cache_key,
                                json.dumps(payload),
                                ex=_IDEMPOTENCY_TTL,
                            )

                        return Response(
                            content=body_bytes,
                            status_code=response.status_code,
                            headers=dict(response.headers),
                            media_type=response.media_type,
                        )
                    return response
                finally:
                    await redis.aclose()


        def _cache_key(method: str, path: str, key: str) -> str:
            raw = f"{{method}}|{{path}}|{{key}}"
            digest = hashlib.sha256(raw.encode()).hexdigest()
            return f"idempotency:{{digest}}"


        async def _get_redis():
            """Return an async Redis client or None if unavailable."""
            try:
                import redis.asyncio as aioredis
            except ImportError:
                return None
            try:
                return aioredis.from_url(
                    settings.REDIS_URL, decode_responses=True
                )
            except Exception as exc:
                _log.warning("idempotency_redis_unavailable", exc_info=exc)
                return None
    ''')

    file_path = out / "idempotency.py"
    file_path.write_text(content)

    return {
        "files_created": [str(file_path)],
        "notes": [
            "Generated middleware/idempotency.py with Idempotency-Key cache.",
            f"TTL: {ttl_seconds}s. Requires Redis; fails open if unavailable.",
        ],
    }
