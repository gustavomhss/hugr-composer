"""Behavioral end-to-end scenarios for ChangeDataCapture — proves invariants at runtime."""

from __future__ import annotations

import pytest

from ChangeDataCapture import (
    ChangeDataCaptureInvariantError,
    Connector,
    InMemoryChangeDataCapture,
)


def test_scenario_source_to_downstream_relay_at_least_once() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id", "total"])
    # Simulate three source-DB transactions.
    for i in range(3):
        cdc.begin_tx(f"tx{i}")
        cdc.stage_change(f"tx{i}", "orders", "insert", i, None, {"id": i, "total": i * 10})
        cdc.commit_tx(f"tx{i}")

    published: list[dict[str, object]] = []
    resume = cdc.checkpoint_of()
    for change in cdc.subscribe("orders", resume):
        if change["op"] == "schema":
            continue
        published.append(dict(change))
        cdc.checkpoint(int(change["pos"]))  # type: ignore[arg-type]
    assert len(published) == 3
    # Consumer restarts — no replay.
    replay = [e for e in cdc.subscribe("orders", cdc.checkpoint_of()) if e["op"] != "schema"]
    assert replay == []


def test_scenario_rollback_hides_uncommitted_changes() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    cdc.begin_tx("tx-good")
    cdc.stage_change("tx-good", "orders", "insert", 1, None, {"id": 1})
    cdc.commit_tx("tx-good")

    cdc.begin_tx("tx-abort")
    cdc.stage_change("tx-abort", "orders", "insert", 99, None, {"id": 99})
    cdc.rollback_tx("tx-abort")

    keys = [e["key"] for e in cdc.subscribe("orders", 0) if e["op"] != "schema"]
    assert keys == [1]


def test_scenario_schema_evolution_forces_consumer_reload() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id", "total"])
    cdc.begin_tx("tx1")
    cdc.stage_change("tx1", "orders", "insert", 1, None, {"id": 1, "total": 10})
    cdc.commit_tx("tx1")
    assert cdc.schema("orders")["schema_version"] == 1
    cdc.evolve_schema("orders", ["id", "total", "currency"])
    assert cdc.schema("orders")["schema_version"] == 2

    # Consumer sees the schema event between the two row events and can reload.
    events = list(cdc.subscribe("orders", 0))
    schema_events = [e for e in events if e["op"] == "schema"]
    assert len(schema_events) == 2  # v1 register + v2 evolve
    assert int(schema_events[-1]["schema_version"]) == 2  # type: ignore[arg-type]


def test_scenario_connector_transaction_atomic_publish() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("orders", ["id"])
    conn = Connector(cdc)
    changes = [
        ("orders", "insert", 1, None, {"id": 1}),
        ("orders", "update", 1, {"id": 1}, {"id": 1, "ready": True}),
        ("orders", "insert", 2, None, {"id": 2}),
    ]
    published = conn.publish_transaction("txn-1", changes)
    assert published == 3
    events = [e for e in cdc.subscribe("orders", 0) if e["op"] != "schema"]
    # In-transaction ordering preserved.
    assert [(e["op"], e["key"]) for e in events] == [
        ("insert", 1),
        ("update", 1),
        ("insert", 2),
    ]


def test_scenario_commit_order_across_transactions_preserved() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("a")
    cdc.stage_change("a", "t", "insert", 10, None, {"id": 10})
    cdc.begin_tx("b")
    cdc.stage_change("b", "t", "insert", 20, None, {"id": 20})
    # Interleaved staging — but commit order determines stream order.
    cdc.commit_tx("b")
    cdc.commit_tx("a")

    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    # tx b committed first → lower pos than tx a.
    assert [e["txid"] for e in events] == ["b", "a"]


def test_scenario_checkpoint_prevents_replay_after_crash() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(4):
        cdc.begin_tx(f"x{i}")
        cdc.stage_change(f"x{i}", "t", "insert", i, None, {"id": i})
        cdc.commit_tx(f"x{i}")

    consumer_applied: list[int] = []
    for ev in cdc.subscribe("t", cdc.checkpoint_of()):
        if ev["op"] == "schema":
            continue
        consumer_applied.append(int(ev["key"]))  # type: ignore[arg-type]
        cdc.checkpoint(int(ev["pos"]))  # type: ignore[arg-type]
    assert consumer_applied == [0, 1, 2, 3]

    # Crash + restart — consumer picks up from the persisted checkpoint, sees nothing new.
    replay = [e for e in cdc.subscribe("t", cdc.checkpoint_of()) if e["op"] != "schema"]
    assert replay == []


def test_scenario_subscribe_unregistered_table_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    with pytest.raises(ChangeDataCaptureInvariantError):
        list(cdc.subscribe("ghost", 0))
