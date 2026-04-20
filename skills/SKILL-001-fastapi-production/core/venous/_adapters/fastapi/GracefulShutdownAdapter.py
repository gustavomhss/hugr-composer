"""FastAPI adapter over the `GracefulShutdown` primitive.

Wires the framework-agnostic state machine
(`core.venous.resiliency.GracefulShutdown.GracefulShutdown`) to FastAPI's
shutdown event and a drain middleware in ≤ 30 lines of glue.

Usage::

    from fastapi import FastAPI
    from core.venous._adapters.fastapi.GracefulShutdownAdapter import install

    app = FastAPI()
    install(app, drain_seconds=5, timeout_seconds=30)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from core.venous.resiliency.GracefulShutdown.GracefulShutdown import GracefulShutdown

_PASS_THROUGH = frozenset({"/healthz", "/readyz"})


def install(app: FastAPI, *, drain_seconds: float = 5.0, timeout_seconds: float = 30.0) -> GracefulShutdown:
    """Install the primitive on *app*; return the live coordinator."""
    sd = GracefulShutdown(drain_seconds=drain_seconds, timeout_seconds=timeout_seconds)

    @app.on_event("startup")
    async def _register() -> None:
        try:
            sd.register()
        except Exception:  # noqa: BLE001 — primitive sets handlers best-effort
            pass

    @app.middleware("http")
    async def _drain(request: Request, call_next):  # noqa: ANN001 — FastAPI callable
        if sd.is_draining() and request.url.path not in _PASS_THROUGH:
            return JSONResponse({"detail": "draining"}, status_code=503, headers={"Retry-After": "10"})
        sd.increment_in_flight()
        try:
            return await call_next(request)
        finally:
            sd.decrement_in_flight()

    @app.on_event("shutdown")
    async def _wait() -> None:
        await sd.wait_complete()

    app.state.graceful_shutdown = sd
    return sd
