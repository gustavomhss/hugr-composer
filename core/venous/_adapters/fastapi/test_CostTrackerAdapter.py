"""Tests for the FastAPI `CostTrackerAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import CostTrackerAdapter

    assert hasattr(CostTrackerAdapter, "install")


def test_install_attaches_tracker_with_default_estimators() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.CostTrackerAdapter import install
    from core.venous.resiliency.CostTracker.CostTracker import CostTracker

    app = FastAPI()
    tracker = install(app)
    assert isinstance(tracker, CostTracker)
    assert app.state.cost_tracker is tracker
    assert len(tracker._estimators) == 3  # db, s3, api
    assert {e.component for e in tracker._estimators} == {"db", "s3", "api"}


def test_middleware_annotates_response_header() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.CostTrackerAdapter import install

    app = FastAPI()
    install(app)

    @app.get("/work")
    async def _w() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as c:
        resp = c.get("/work")
    assert resp.status_code == 200
    assert "X-Request-Cost-Estimate" in resp.headers
    assert resp.headers["X-Request-Cost-Estimate"].startswith("$")
    assert "X-Request-Id" in resp.headers


def test_skip_path_bypasses_middleware() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.CostTrackerAdapter import install

    app = FastAPI()
    install(app)

    @app.get("/healthz")
    async def _h() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as c:
        resp = c.get("/healthz")
    assert "X-Request-Cost-Estimate" not in resp.headers


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_tracker_with_default_estimators,
        test_middleware_annotates_response_header,
        test_skip_path_bypasses_middleware,
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
