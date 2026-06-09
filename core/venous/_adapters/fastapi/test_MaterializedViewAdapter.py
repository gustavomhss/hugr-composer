"""Tests for the FastAPI `MaterializedViewAdapter` (CQRS read model, auth-gated)."""

from __future__ import annotations

from types import SimpleNamespace


def _fake_auth() -> object:
    """Stand-in auth dependency returning a superuser principal."""
    return SimpleNamespace(email="admin@example.com", id="u-1")


class _FakeStore:
    """Minimal EventSourcedStore-shaped stub: per-aggregate event lists."""

    def __init__(self, streams: dict[str, list[dict]]) -> None:
        self._streams = streams

    def load(self, aggregate_id: str) -> list[dict]:
        return list(self._streams.get(aggregate_id, []))


def _build_view():
    from core.venous._adapters.fastapi.MaterializedViewAdapter import make_view

    view = make_view("orders", schema_version=1)

    @view.on("created")
    def _on_created(rows: dict, event: dict) -> None:  # noqa: ANN001
        rows[event["aggregate_id"]] = {
            "id": event["aggregate_id"],
            "status": "created",
            "schema_version": event["schema_version"],
        }

    @view.on("shipped")
    def _on_shipped(rows: dict, event: dict) -> None:  # noqa: ANN001
        rows[event["aggregate_id"]]["status"] = "shipped"

    return view


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import MaterializedViewAdapter

    assert callable(MaterializedViewAdapter.install)
    assert callable(MaterializedViewAdapter.rebuild_from_store)
    assert callable(MaterializedViewAdapter.make_view)


def test_install_attaches_views_and_router() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    app = FastAPI()
    views = install(app, store=_FakeStore({}), auth_dependency=_fake_auth, views={})
    assert app.state.materialized_views is views
    paths = [r.path for r in app.router.routes]
    assert any("/projections" in p for p in paths)


def test_rebuild_from_store_projects_per_aggregate_grain() -> None:
    """rebuild_from_store maps store events → MV shape using per-aggregate seq."""
    from core.venous._adapters.fastapi.MaterializedViewAdapter import rebuild_from_store

    view = _build_view()
    store = _FakeStore(
        {
            "ord-1": [{"type": "created"}, {"type": "shipped"}],
            "ord-2": [{"type": "created"}],
        }
    )
    applied = rebuild_from_store(view, store, ["ord-1", "ord-2"])
    assert applied == 3
    rows = {r["id"]: r for r in view.query(None)}
    assert rows["ord-1"]["status"] == "shipped"
    assert rows["ord-2"]["status"] == "created"


def test_rebuild_is_idempotent_at_least_once() -> None:
    """Re-applying the same suffix is dropped (seq <= last_applied)."""
    from core.venous._adapters.fastapi.MaterializedViewAdapter import rebuild_from_store

    view = _build_view()
    store = _FakeStore({"ord-1": [{"type": "created"}, {"type": "shipped"}]})
    rebuild_from_store(view, store, ["ord-1"])
    # Replaying the same stream again applies nothing new (idempotent).
    again = rebuild_from_store(view, store, ["ord-1"])
    assert again == 0
    rows = list(view.query(None))
    assert len(rows) == 1
    assert rows[0]["status"] == "shipped"


def test_query_route_returns_projected_rows() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.MaterializedViewAdapter import (
        install,
        rebuild_from_store,
    )

    view = _build_view()
    store = _FakeStore({"ord-1": [{"type": "created"}]})
    rebuild_from_store(view, store, ["ord-1"])

    app = FastAPI()
    install(app, store=store, auth_dependency=_fake_auth, views={"orders": view})
    client = TestClient(app)

    r = client.get("/projections/orders")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["view"] == "orders"
    assert body["rows"][0]["id"] == "ord-1"
    assert "stale" in body and "staleness_s" in body


def test_rebuild_route_replays_from_store() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    view = _build_view()
    store = _FakeStore(
        {"ord-1": [{"type": "created"}, {"type": "shipped"}], "ord-2": [{"type": "created"}]}
    )

    app = FastAPI()
    install(
        app,
        store=store,
        auth_dependency=_fake_auth,
        views={"orders": view},
        aggregate_id_resolver=lambda s: ["ord-1", "ord-2"],
    )
    client = TestClient(app)

    r = client.post("/projections/orders/rebuild")
    assert r.status_code == 200, r.text
    assert r.json()["events_applied"] == 3

    rows = {row["id"]: row for row in client.get("/projections/orders").json()["rows"]}
    assert rows["ord-1"]["status"] == "shipped"
    assert rows["ord-2"]["status"] == "created"


def test_rebuild_without_resolver_returns_501() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    view = _build_view()
    app = FastAPI()
    install(app, store=_FakeStore({}), auth_dependency=_fake_auth, views={"orders": view})
    client = TestClient(app)
    assert client.post("/projections/orders/rebuild").status_code == 501


def test_unknown_view_returns_404() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    app = FastAPI()
    install(app, store=_FakeStore({}), auth_dependency=_fake_auth, views={})
    client = TestClient(app)
    assert client.get("/projections/nope").status_code == 404


def test_routes_require_auth() -> None:
    """A failing auth dependency blocks query AND rebuild (R5-O2-D6 mirror)."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.MaterializedViewAdapter import install

    def _deny() -> object:
        raise HTTPException(status_code=401, detail="unauthenticated")

    view = _build_view()
    app = FastAPI()
    install(
        app,
        store=_FakeStore({}),
        auth_dependency=_deny,
        views={"orders": view},
        aggregate_id_resolver=lambda s: [],
    )
    client = TestClient(app)
    assert client.get("/projections/orders").status_code == 401
    assert client.post("/projections/orders/rebuild").status_code == 401


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_views_and_router,
        test_rebuild_from_store_projects_per_aggregate_grain,
        test_rebuild_is_idempotent_at_least_once,
        test_query_route_returns_projected_rows,
        test_rebuild_route_replays_from_store,
        test_rebuild_without_resolver_returns_501,
        test_unknown_view_returns_404,
        test_routes_require_auth,
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
