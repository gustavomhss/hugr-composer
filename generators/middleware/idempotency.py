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
                """Process a request applying idempotency-key cache semantics.

                For mutating methods with an ``Idempotency-Key`` header, checks
                Redis for a cached response and returns it immediately on a hit.
                On a miss, executes the request and caches 2xx/4xx responses.
                Passes through unchanged if Redis is unavailable (fail-open).

                Args:
                    request: Incoming Starlette request.
                    call_next: Next middleware / route handler in the chain.

                Returns:
                    Cached JSON response on duplicate, or the live response.
                """
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
                    cached_response = await _check_cache(redis, cache_key)
                    if cached_response is not None:
                        return cached_response

                    response = await call_next(request)
                    return await _store_response(redis, cache_key, response)
                finally:
                    await redis.aclose()


        async def _check_cache(redis, cache_key: str):
            """Return a cached JSONResponse if one exists, else None.

            Args:
                redis: Async Redis client.
                cache_key: Computed idempotency cache key.

            Returns:
                A ``JSONResponse`` built from the cached payload, or ``None``.
            """
            cached = await redis.get(cache_key)
            if cached is None:
                return None
            try:
                payload = json.loads(cached)
                return JSONResponse(
                    status_code=payload["status"],
                    content=payload["body"],
                    headers=payload.get("headers", {{}}),
                )
            except (json.JSONDecodeError, KeyError):
                _log = logging.getLogger(__name__)
                _log.warning("idempotency_cache_corrupt", extra={{"key": cache_key}})
                return None


        async def _store_response(redis, cache_key: str, response: Response) -> Response:
            """Cache a cacheable response and return a re-readable Response.

            Only caches 2xx and 4xx responses (skips 5xx so retries are safe).
            Returns a new ``Response`` with the body bytes already read so the
            caller can forward it downstream.

            Args:
                redis: Async Redis client.
                cache_key: Computed idempotency cache key.
                response: The live response from the route handler.

            Returns:
                A ``Response`` whose body has been read and can be forwarded.
            """
            if not (200 <= response.status_code < 500):
                return response

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
                await redis.set(cache_key, json.dumps(payload), ex=_IDEMPOTENCY_TTL)

            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )


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
