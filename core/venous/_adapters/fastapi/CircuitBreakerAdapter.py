"""FastAPI adapter over the `CircuitBreaker` primitive.

Exposes a named-breaker registry and a ``Depends``-compatible helper so
route handlers can wrap external-dependency calls in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI, Depends
    from core.venous._adapters.fastapi.CircuitBreakerAdapter import install, breaker

    app = FastAPI()
    install(app)

    @app.get("/users/{uid}")
    async def read(uid: str, cb=Depends(breaker("user_service"))):
        return await cb.call(fetch_user, uid)
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI

from core.venous.resiliency.CircuitBreaker.CircuitBreaker import InMemoryCircuitBreaker


def install(app: FastAPI) -> dict[str, InMemoryCircuitBreaker]:
    """Attach a fresh registry to ``app.state.circuit_breakers`` and return it."""
    registry: dict[str, InMemoryCircuitBreaker] = {}
    app.state.circuit_breakers = registry
    return registry


def get_breaker(
    app: FastAPI,
    name: str,
    *,
    failure_rate_threshold: float = 0.5,
    minimum_number_of_calls: int = 5,
    cooldown_ms: int = 1_000,
) -> InMemoryCircuitBreaker:
    """Return the named breaker from the registry, creating it on first use."""
    registry: dict[str, InMemoryCircuitBreaker] = app.state.circuit_breakers
    cb = registry.get(name)
    if cb is None:
        cb = InMemoryCircuitBreaker(
            name,
            failure_rate_threshold=failure_rate_threshold,
            minimum_number_of_calls=minimum_number_of_calls,
            cooldown_ms=cooldown_ms,
        )
        registry[name] = cb
    return cb


def breaker(name: str, **kw: object) -> Callable[..., InMemoryCircuitBreaker]:
    """Return a FastAPI ``Depends``-compatible factory for breaker *name*."""
    from fastapi import Request

    def _dep(request: Request) -> InMemoryCircuitBreaker:
        return get_breaker(request.app, name, **kw)  # type: ignore[arg-type]

    return _dep
