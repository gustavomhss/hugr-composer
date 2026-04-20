"""Tests for the FastAPI `UnitOfWorkAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import UnitOfWorkAdapter

    assert hasattr(UnitOfWorkAdapter, "get_uow")
    assert hasattr(UnitOfWorkAdapter, "make_dependency")


def test_dependency_commits_on_clean_exit() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency

    flushed: list[tuple[int, int, int]] = []

    def _flush(new: list[object], dirty: list[object], removed: list[object]) -> None:
        flushed.append((len(new), len(dirty), len(removed)))

    dep = make_dependency(_flush)
    app = FastAPI()

    @app.post("/items")
    async def create(uow=Depends(dep)) -> dict:
        uow.register_new(object())
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/items").status_code == 200

    assert flushed == [(1, 0, 0)]


def test_dependency_rolls_back_on_exception() -> None:
    from fastapi import Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency

    flushed: list[object] = []
    dep = make_dependency(lambda n, d, r: flushed.append("FLUSHED"))
    app = FastAPI()

    @app.post("/fail")
    async def create(uow=Depends(dep)) -> dict:  # pragma: no cover
        uow.register_new(object())
        raise HTTPException(status_code=418)

    with TestClient(app) as client:
        assert client.post("/fail").status_code == 418

    assert flushed == []  # rollback path → flush never fired


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_dependency_commits_on_clean_exit,
        test_dependency_rolls_back_on_exception,
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
