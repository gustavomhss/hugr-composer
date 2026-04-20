"""Tests for the FastAPI `SagaAdapter`."""

from __future__ import annotations


def _make_definition():
    from core.venous.events.SagaOrchestrator.SagaOrchestrator import SagaDefinition

    d = SagaDefinition("test_saga")
    d.register("reserve", compensator=lambda payload: None)(lambda payload: {"ok": True})
    d.register("charge", compensator=lambda payload: None)(lambda payload: {"ok": True})
    return d


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import SagaAdapter

    assert callable(SagaAdapter.install)


def test_install_attaches_orchestrator_and_router() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.SagaAdapter import install

    app = FastAPI()
    orch = install(app, definition=_make_definition())
    assert app.state.saga_orchestrator is orch
    # Router mounted
    paths = [r.path for r in app.router.routes]
    assert any("/admin/sagas" in p for p in paths)


def test_start_status_roundtrip() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.SagaAdapter import install

    app = FastAPI()
    install(app, definition=_make_definition())
    client = TestClient(app)
    r = client.post("/admin/sagas/corr-1/start", json={"cart": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["correlation_id"] == "corr-1"
    assert body["state"] in {"running", "pending", "completed"}

    r2 = client.get("/admin/sagas/corr-1")
    assert r2.status_code == 200


if __name__ == "__main__":
    import sys
    tests = [test_adapter_imports_cleanly, test_install_attaches_orchestrator_and_router, test_start_status_roundtrip]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); failed += 1
    sys.exit(1 if failed else 0)
