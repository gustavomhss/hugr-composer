"""Chaos / game-day tests for ChangeDataCapture.

Simulates:
- connector crash mid-transaction → no dirty reads surface (CDC-INV-03);
- malformed change flood → every malformed input rejected, log unchanged;
- duplicate commit attempts → second commit rejected, log stays consistent;
- checkpoint rewind flood → every attempt rejected, stored position holds;
- schema evolution under live load → row events always post-date their schema event;
- massive transaction (10_000 stages) followed by a subscribe call — stream is
  ordered and position-monotonic.
"""

from __future__ import annotations

import pytest

from ChangeDataCapture import (
    ChangeDataCaptureInvariantError,
    Connector,
    InMemoryChangeDataCapture,
)


def test_chaos_connector_crash_rolls_back_transaction() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    conn = Connector(cdc)

    def changes_that_crash():  # type: ignore[no-untyped-def]
        yield ("t", "insert", 1, None, {"id": 1})
        yield ("t", "insert", 2, None, {"id": 2})
        raise RuntimeError("upstream socket reset")

    with pytest.raises(RuntimeError):
        conn.publish_transaction("tx-crash", changes_that_crash())
    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    assert events == []


def test_chaos_malformed_stage_flood_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("tx")
    # A barrage of malformed stage attempts.
    bad_ops = ["upsert", "merge", "", "INSERT"]
    for op in bad_ops:
        with pytest.raises(ChangeDataCaptureInvariantError):
            cdc.stage_change("tx", "t", op, 1, None, {"id": 1})
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.stage_change("tx", "ghost", "insert", 1, None, {"id": 1})
    cdc.rollback_tx("tx")
    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    assert events == []


def test_chaos_double_commit_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("once")
    cdc.stage_change("once", "t", "insert", 1, None, {"id": 1})
    cdc.commit_tx("once")
    for _ in range(10):
        with pytest.raises(ChangeDataCaptureInvariantError):
            cdc.commit_tx("once")
    assert cdc.committed_event_count == 1


def test_chaos_checkpoint_rewind_flood_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("t")
    cdc.stage_change("t", "t", "insert", 1, None, {"id": 1})
    cdc.commit_tx("t")
    cdc.checkpoint(500)
    for i in range(100):
        with pytest.raises(ChangeDataCaptureInvariantError):
            cdc.checkpoint(i)
    assert cdc.checkpoint_of() == 500


def test_chaos_schema_evolution_under_load() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    # Emit some events, evolve, emit some more, repeat.
    tx_counter = 0
    for cycle in range(5):
        for _ in range(10):
            cdc.begin_tx(f"x{tx_counter}")
            cdc.stage_change(f"x{tx_counter}", "t", "insert", tx_counter, None, {"id": tx_counter})
            cdc.commit_tx(f"x{tx_counter}")
            tx_counter += 1
        cdc.evolve_schema("t", [f"id_v{cycle}", f"ver{cycle}"])

    # Walk the stream and verify schema-ordering invariant.
    current_v = 0
    schema_events = 0
    row_events = 0
    for ev in cdc.subscribe("t", 0):
        if ev["op"] == "schema":
            assert int(ev["schema_version"]) == current_v + 1  # type: ignore[arg-type]
            current_v = int(ev["schema_version"])  # type: ignore[arg-type]
            schema_events += 1
        else:
            row_events += 1
            assert int(ev["schema_version"]) <= current_v  # type: ignore[arg-type]
    assert schema_events == 6  # v1 register + 5 evolves
    assert row_events == 50


def test_chaos_massive_single_transaction() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    N = 10_000
    cdc.begin_tx("big")
    for i in range(N):
        cdc.stage_change("big", "t", "insert", i, None, {"id": i})
    published = cdc.commit_tx("big")
    assert published == N
    events = [e for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    assert len(events) == N
    positions = [int(e["pos"]) for e in events]  # type: ignore[arg-type]
    assert positions == sorted(positions)


def test_chaos_oversized_transaction_rejected() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("huge")
    limit = 100_000
    for i in range(limit):
        cdc.stage_change("huge", "t", "insert", i, None, {"id": i})
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.stage_change("huge", "t", "insert", limit, None, {"id": limit})
    cdc.rollback_tx("huge")


def test_chaos_rollback_then_new_txid_required() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("once")
    cdc.stage_change("once", "t", "insert", 1, None, {"id": 1})
    cdc.rollback_tx("once")
    # Reusing an aborted txid is FORBIDDEN — fresh txid only.
    with pytest.raises(ChangeDataCaptureInvariantError):
        cdc.begin_tx("once")
