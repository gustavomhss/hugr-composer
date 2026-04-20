"""Tests for the FastAPI `LoadShedderAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import LoadShedderAdapter

    assert callable(LoadShedderAdapter.install)


def test_install_attaches_shedder() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.LoadShedderAdapter import install

    app = FastAPI()
    ls = install(app)
    assert app.state.load_shedder is ls


def test_normal_priority_request_admitted() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.LoadShedderAdapter import install

    app = FastAPI()
    install(app)

    @app.get("/ping")
    async def _ping() -> dict:  # pragma: no cover
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200


if __name__ == "__main__":
    import sys
    tests = [test_adapter_imports_cleanly, test_install_attaches_shedder, test_normal_priority_request_admitted]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); failed += 1
    sys.exit(1 if failed else 0)
