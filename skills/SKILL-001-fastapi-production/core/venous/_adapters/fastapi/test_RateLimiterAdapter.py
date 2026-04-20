"""Tests for the FastAPI `RateLimiterAdapter`.

Contracts:

1. Module imports cleanly.
2. ``install(app)`` attaches an ``InMemoryRateLimiter`` to ``app.state``.
3. Middleware emits 429 + Retry-After once the bucket is exhausted.
4. Exempt paths bypass the limiter.

Run with::

    PYTHONPATH=. pytest core/venous/_adapters/fastapi/test_RateLimiterAdapter.py -q
"""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import RateLimiterAdapter

    assert hasattr(RateLimiterAdapter, "install")
    assert callable(RateLimiterAdapter.install)


def test_install_attaches_limiter() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.RateLimiterAdapter import install
    from core.venous.resiliency.RateLimiter.RateLimiter import InMemoryRateLimiter

    app = FastAPI()
    lim = install(app, rate_per_second=10.0, burst=2)
    assert isinstance(lim, InMemoryRateLimiter)
    assert app.state.rate_limiter is lim


def test_exhaustion_returns_429() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.RateLimiterAdapter import install

    app = FastAPI()
    install(app, rate_per_second=0.1, burst=1)

    @app.get("/ping")
    async def _ping() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as c:
        r1 = c.get("/ping")
        r2 = c.get("/ping")
    assert r1.status_code == 200
    assert r2.status_code == 429
    assert "Retry-After" in r2.headers


def test_exempt_path_bypasses_limiter() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.RateLimiterAdapter import install

    app = FastAPI()
    install(app, rate_per_second=0.1, burst=1, exempt_paths=("/healthz",))

    @app.get("/healthz")
    async def _h() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as c:
        for _ in range(5):
            assert c.get("/healthz").status_code == 200


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_limiter,
        test_exhaustion_returns_429,
        test_exempt_path_bypasses_limiter,
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
