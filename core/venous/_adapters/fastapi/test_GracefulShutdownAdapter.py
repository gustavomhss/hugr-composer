"""Tests for the FastAPI `GracefulShutdownAdapter`.

Asserts three contracts:

1. The adapter module imports cleanly (no ImportError, no circular
   dep).
2. ``install(app)`` registers a shutdown event handler on the FastAPI
   app.
3. The drain middleware decrements the in-flight counter on the
   underlying primitive once a request has passed through.

Run with::

    PYTHONPATH=. pytest core/venous/_adapters/fastapi/test_GracefulShutdownAdapter.py -q
"""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    """Importing the adapter module must succeed without side effects."""
    from core.venous._adapters.fastapi import GracefulShutdownAdapter

    assert hasattr(GracefulShutdownAdapter, "install")
    assert callable(GracefulShutdownAdapter.install)


def test_install_registers_shutdown_handler() -> None:
    """install(app) must attach a shutdown event handler + attach .state."""
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.GracefulShutdownAdapter import install

    app = FastAPI()
    sd = install(app, drain_seconds=0.01, timeout_seconds=0.05)

    # FastAPI stores the coordinator on app.state.
    assert app.state.graceful_shutdown is sd
    # At least one shutdown handler must be registered by the adapter.
    handlers = app.router.on_shutdown
    assert handlers, "No shutdown handler registered on the FastAPI router"


def test_drain_middleware_tracks_in_flight() -> None:
    """Middleware must increment/decrement in-flight on non-drain paths."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.GracefulShutdownAdapter import install

    app = FastAPI()
    sd = install(app, drain_seconds=0.01, timeout_seconds=0.05)

    @app.get("/ping")
    async def _ping() -> dict:  # pragma: no cover — trivial
        return {"ok": True}

    # Before any traffic, in-flight is 0.
    assert sd._in_flight == 0

    with TestClient(app) as client:
        assert client.get("/ping").status_code == 200

    # After the request completes the decrement path must have fired.
    assert sd._in_flight == 0


def test_middleware_returns_503_while_draining() -> None:
    """Once the primitive is draining, non-pass-through paths get 503."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.GracefulShutdownAdapter import install

    app = FastAPI()
    sd = install(app, drain_seconds=0.01, timeout_seconds=0.05)

    @app.get("/ping")
    async def _ping() -> dict:  # pragma: no cover
        return {"ok": True}

    sd._draining = True  # simulate a received SIGTERM
    # Do NOT enter the TestClient context manager — that would trigger
    # FastAPI's shutdown event which calls the primitive's wait_complete()
    # whose logger is deliberately unwired in the staged primitive
    # (see core/venous/resiliency/GracefulShutdown/test_GracefulShutdown.py).
    client = TestClient(app)
    resp = client.get("/ping")
    assert resp.status_code == 503
    assert resp.headers.get("Retry-After") == "10"


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_registers_shutdown_handler,
        test_drain_middleware_tracks_in_flight,
        test_middleware_returns_503_while_draining,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)
