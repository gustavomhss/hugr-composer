"""Behavioral end-to-end scenarios for MaterializedView — proves invariants at runtime."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from MaterializedView import (
    InMemoryMaterializedView,
    MaterializedViewInvariantError,
)


def _order_upsert(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    payload = event.get("payload", {})
    assert isinstance(payload, Mapping)
    cur = rows.get(aid, {"aggregate_id": aid})
    cur.update(dict(payload))
    rows[aid] = cur


def _order_shipped(rows: dict[str, dict[str, object]], event: Mapping[str, object]) -> None:
    aid = str(event["aggregate_id"])
    row = rows.get(aid, {"aggregate_id": aid})
    row["status"] = "shipped"
    row["ready_to_serve"] = True
    rows[aid] = row


def _build_view(name: str = "orders", schema_version: int = 1) -> InMemoryMaterializedView:
    v = InMemoryMaterializedView(name, schema_version=schema_version)
    v.register_handler("order.created", _order_upsert)
    v.register_handler("order.updated", _order_upsert)
    v.register_handler("order.shipped", _order_shipped)
    return v


def _ev(seq: int, etype: str, aid: str, payload: dict[str, object] | None = None, version: int = 1) -> dict[str, object]:
    return {
        "type": etype,
        "aggregate_id": aid,
        "seq": seq,
        "schema_version": version,
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# End-to-end scenarios
# ---------------------------------------------------------------------------
def test_scenario_stream_shapes_read_model() -> None:
    view = _build_view()
    view.apply(_ev(1, "order.created", "o1", {"total": 100, "status": "pending"}))
    view.apply(_ev(2, "order.updated", "o1", {"total": 120}))
    view.apply(_ev(3, "order.shipped", "o1"))
    rows = list(view.query({"ready_to_serve": True}))
    assert rows == [{"aggregate_id": "o1", "total": 120, "status": "shipped", "ready_to_serve": True}]


def test_scenario_full_rebuild_from_source_feed() -> None:
    source = [
        _ev(1, "order.created", "o1", {"total": 50}),
        _ev(2, "order.created", "o2", {"total": 75}),
        _ev(3, "order.shipped", "o1"),
    ]
    view = _build_view()
    view.rebuild(source)
    assert len(list(view.query(None))) == 2
    assert list(view.query({"status": "shipped"})) == [
        {"aggregate_id": "o1", "total": 50, "status": "shipped", "ready_to_serve": True}
    ]


def test_scenario_staleness_surfaces_to_caller() -> None:
    fake_time = [1000.0]

    def clock() -> float:
        return fake_time[0]

    view = InMemoryMaterializedView("orders", max_age_s=2.0, clock=clock)
    view.register_handler("order.created", _order_upsert)
    view.apply(_ev(1, "order.created", "o1", {"total": 100}))
    assert view.is_fresh()
    fake_time[0] += 5.0
    # Caller sees unambiguous staleness — no linearizability fiction.
    assert not view.is_fresh()
    assert view.staleness_s() >= 5.0


def test_scenario_schema_evolution_forces_rebuild() -> None:
    view = _build_view(schema_version=1)
    view.rebuild([_ev(1, "order.created", "o1", {"total": 100}, version=1)])
    assert list(view.query(None))

    view.evolve_schema(2)
    # Queries refuse until rebuild at v2.
    with pytest.raises(MaterializedViewInvariantError):
        list(view.query(None))

    view.rebuild([_ev(1, "order.created", "o1", {"total": 100}, version=2)])
    assert list(view.query(None))


def test_scenario_source_to_view_convergence_across_replicas() -> None:
    # Two replicas consuming the same ordered stream converge to the same contents.
    stream = [
        _ev(1, "order.created", "o1", {"total": 10}),
        _ev(2, "order.created", "o2", {"total": 20}),
        _ev(3, "order.updated", "o1", {"total": 15}),
        _ev(4, "order.shipped", "o2"),
    ]
    replica_a = _build_view()
    replica_b = _build_view()
    for e in stream:
        replica_a.apply(e)
    # Replica B rebuilds from the same feed.
    replica_b.rebuild(stream)
    assert replica_a.rows() == replica_b.rows()


def test_scenario_at_least_once_delivery_is_idempotent() -> None:
    # CDC / broker redelivers seq=2 multiple times; the view converges once.
    view = _build_view()
    stream = [
        _ev(1, "order.created", "o1", {"total": 10}),
        _ev(2, "order.updated", "o1", {"total": 20}),
        _ev(2, "order.updated", "o1", {"total": 20}),
        _ev(2, "order.updated", "o1", {"total": 20}),
    ]
    for e in stream:
        view.apply(e)
    assert view.applied_event_count == 2
    rows = list(view.query({"aggregate_id": "o1"}))
    assert rows == [{"aggregate_id": "o1", "total": 20}]
