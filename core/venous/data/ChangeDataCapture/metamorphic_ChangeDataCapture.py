"""Metamorphic + differential tests for ChangeDataCapture.

Algebraic properties:
- Deterministic replay: two CDC instances receiving the same tx sequence produce
  identical committed logs (differential).
- Idempotent subscribe: subscribing twice from the same position returns the
  same snapshot.
- Commit-order equivalence: interleaved staging but strictly ordered commits
  yields a stream ordered by commit time, not stage time.
- Rollback is a left-identity on the committed log.
- Checkpoint monotonicity: advancing a checkpoint twice is equivalent to
  advancing once with max(positions).
- Schema evolution is append-only in the position axis: evolve_schema never
  mutates prior schema events.
"""

from __future__ import annotations

from ChangeDataCapture import InMemoryChangeDataCapture


def _commit_simple(cdc: InMemoryChangeDataCapture, txid: str, key: int, value: int) -> None:
    cdc.begin_tx(txid)
    cdc.stage_change(txid, "t", "insert", key, None, {"id": key, "v": value})
    cdc.commit_tx(txid)


def test_metamorphic_differential_two_replicas_identical_log() -> None:
    a = InMemoryChangeDataCapture()
    b = InMemoryChangeDataCapture()
    for cdc in (a, b):
        cdc.register_table("t", ["id", "v"])
        for i in range(1, 11):
            _commit_simple(cdc, f"t{i}", i, i * 2)

    la = [(e["op"], e["table"], e["txid"], e["pos"]) for e in a.log_snapshot()]
    lb = [(e["op"], e["table"], e["txid"], e["pos"]) for e in b.log_snapshot()]
    assert la == lb


def test_metamorphic_subscribe_is_idempotent() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(5):
        _commit_simple(cdc, f"t{i}", i, i)
    snap1 = list(cdc.subscribe("t", 0))
    snap2 = list(cdc.subscribe("t", 0))
    assert snap1 == snap2


def test_metamorphic_commit_order_not_stage_order() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    cdc.begin_tx("a")
    cdc.stage_change("a", "t", "insert", 100, None, {"id": 100})
    cdc.begin_tx("b")
    cdc.stage_change("b", "t", "insert", 200, None, {"id": 200})
    cdc.begin_tx("c")
    cdc.stage_change("c", "t", "insert", 300, None, {"id": 300})

    cdc.commit_tx("c")
    cdc.commit_tx("a")
    cdc.commit_tx("b")

    txids = [e["txid"] for e in cdc.subscribe("t", 0) if e["op"] != "schema"]
    assert txids == ["c", "a", "b"]


def test_metamorphic_rollback_is_left_identity_on_log() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    _commit_simple(cdc, "good", 1, 1)
    before = cdc.log_snapshot()
    cdc.begin_tx("abort")
    cdc.stage_change("abort", "t", "insert", 999, None, {"id": 999})
    cdc.rollback_tx("abort")
    after = cdc.log_snapshot()
    # Rollback does not append anything to the committed log.
    assert before == after


def test_metamorphic_checkpoint_monotonicity() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(5):
        _commit_simple(cdc, f"t{i}", i, i)
    cdc.checkpoint(3)
    cdc.checkpoint(7)
    cdc.checkpoint(7)  # idempotent at the current value
    assert cdc.checkpoint_of() == 7


def test_metamorphic_schema_events_append_only() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    v1_log = [dict(e) for e in cdc.log_snapshot() if e["op"] == "schema"]
    cdc.evolve_schema("t", ["id", "x"])
    cdc.evolve_schema("t", ["id", "x", "y"])
    schema_log = [dict(e) for e in cdc.log_snapshot() if e["op"] == "schema"]
    # First entry (v1) is byte-identical to the original registration.
    assert schema_log[0] == v1_log[0]
    versions = [int(e["schema_version"]) for e in schema_log]  # type: ignore[arg-type]
    assert versions == [1, 2, 3]


def test_differential_row_count_matches_committed_events() -> None:
    cdc = InMemoryChangeDataCapture()
    cdc.register_table("t", ["id"])
    for i in range(1, 21):
        _commit_simple(cdc, f"tx{i}", i, i)
    row_events = [e for e in cdc.log_snapshot() if e["op"] != "schema"]
    assert len(row_events) == 20
    assert cdc.committed_event_count == 20
