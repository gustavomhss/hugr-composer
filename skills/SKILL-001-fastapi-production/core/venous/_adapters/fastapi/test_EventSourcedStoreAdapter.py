"""Tests for the FastAPI `EventSourcedStoreAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import EventSourcedStoreAdapter

    assert callable(EventSourcedStoreAdapter.install)


def test_install_attaches_store_and_router() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install

    app = FastAPI()
    store = install(app)
    assert app.state.event_store is store
    paths = [r.path for r in app.router.routes]
    assert any("/events" in p for p in paths)


def test_append_and_load_roundtrip() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install

    app = FastAPI()
    install(app)
    client = TestClient(app)

    r = client.post("/events/agg-1?expected_version=0", json=[{"type": "created", "data": {"x": 1}}])
    assert r.status_code == 200, r.text
    assert r.json()["version"] == 1

    r2 = client.get("/events/agg-1")
    assert r2.status_code == 200
    assert r2.json()["version"] == 1


def test_concurrency_conflict_returns_409() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.EventSourcedStoreAdapter import install

    app = FastAPI()
    install(app)
    client = TestClient(app)
    client.post("/events/agg-2?expected_version=0", json=[{"type": "a", "data": {}}])
    r = client.post("/events/agg-2?expected_version=0", json=[{"type": "a", "data": {}}])
    assert r.status_code == 409


if __name__ == "__main__":
    import sys
    tests = [test_adapter_imports_cleanly, test_install_attaches_store_and_router, test_append_and_load_roundtrip, test_concurrency_conflict_returns_409]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); failed += 1
    sys.exit(1 if failed else 0)
