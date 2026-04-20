"""FastAPI adapter over the `RateLimiter` primitive.

Wires :class:`InMemoryRateLimiter` to a FastAPI middleware that emits
RFC-6585 429 responses with a ``Retry-After`` header. ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.RateLimiterAdapter import install

    app = FastAPI()
    install(app, rate_per_second=100.0, burst=200, key="ip")
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from core.venous.resiliency.RateLimiter.RateLimiter import InMemoryRateLimiter

KeyStrategy = Literal["ip", "user", "user_endpoint"]


def install(
    app: FastAPI,
    *,
    rate_per_second: float = 100.0,
    burst: int = 200,
    key: KeyStrategy = "ip",
    exempt_paths: tuple[str, ...] = ("/healthz", "/readyz", "/docs", "/openapi.json"),
) -> InMemoryRateLimiter:
    """Install the limiter on *app*; return the live primitive."""
    limiter = InMemoryRateLimiter(rate_per_second=rate_per_second, burst=burst)

    def _key(req: Request) -> str:
        if key == "user":
            u = getattr(req.state, "user", None)
            return f"user:{getattr(u, 'id', 'anon')}"
        if key == "user_endpoint":
            u = getattr(req.state, "user", None)
            return f"user:{getattr(u, 'id', 'anon')}:{req.url.path}"
        return f"ip:{req.client.host if req.client else 'unknown'}"

    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):  # noqa: ANN001
        if request.url.path in exempt_paths:
            return await call_next(request)
        k = _key(request)
        if not limiter.try_acquire(k, cost=1):
            retry_s = max(1, (limiter.events[-1].retry_after_ms if limiter.events else 1000) // 1000)
            return JSONResponse({"detail": "rate limited"}, status_code=429, headers={"Retry-After": str(retry_s)})
        return await call_next(request)

    app.state.rate_limiter = limiter
    return limiter
