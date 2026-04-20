"""Behavioral end-to-end scenarios for EventStream — proves invariants at runtime."""

from __future__ import annotations

import pytest

from EventStream import (
    EventStreamInvariantError,
    InMemoryEventStream,
    StageAdapter,
)


def test_scenario_partitioned_append_and_tail_is_head() -> None:
    es = InMemoryEventStream()
    # Two partitions receive events interleaved.
    for i in range(3):
        es.append("orders", {"id": i})
        es.append("payments", {"id": i})
    assert es.tail("orders") == 4
    assert es.tail("payments") == 4
    # Per-partition seqs start at 1 and are independent.
    orders_seqs = [int(e["seq"]) for e in es.log_snapshot("orders")]  # type: ignore[arg-type]
    pays_seqs = [int(e["seq"]) for e in es.log_snapshot("payments")]  # type: ignore[arg-type]
    assert orders_seqs == [1, 2, 3]
    assert pays_seqs == [1, 2, 3]


def test_scenario_many_consumers_independent_cursors() -> None:
    es = InMemoryEventStream()
    for i in range(5):
        es.append("p", {"i": i})
    # Two independent consumers start at different offsets; neither mutates
    # the log, and both can re-read from their own cursor.
    a_events = list(es.read_from("p", 0))
    b_events = list(es.read_from("p", 3))
    assert len(a_events) == 5
    assert len(b_events) == 3
    # Replay is deterministic — consumer A can re-read its cursor any time.
    again = list(es.read_from("p", 0))
    assert again == a_events


def test_scenario_replay_from_middle_is_deterministic() -> None:
    es = InMemoryEventStream()
    for i in range(10):
        es.append("p", {"i": i})
    # Read 3 times from offset 5 — always get the same suffix.
    r1 = list(es.read_from("p", 5))
    r2 = list(es.read_from("p", 5))
    r3 = list(es.read_from("p", 5))
    assert r1 == r2 == r3
    assert [int(e["i"]) for e in r1] == [4, 5, 6, 7, 8, 9]  # type: ignore[arg-type]


def test_scenario_retention_driven_truncation_compacts_history() -> None:
    es = InMemoryEventStream(retention_min_entries=3)
    for i in range(8):
        es.append("p", {"i": i})
    # Keep at least 3 entries; truncating to seq=6 leaves seqs 6,7,8.
    es.truncate_before(6)
    remaining = list(es.read_from("p", 6))
    assert [int(e["i"]) for e in remaining] == [5, 6, 7]  # type: ignore[arg-type]
    # Reader that still holds the old cursor is told — loudly — that its
    # replay range was evicted.
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("p", 0))


def test_scenario_stage_pipeline_preserves_per_partition_order() -> None:
    es = InMemoryEventStream()

    def tag_with_source(_key: str, event: object) -> object:
        if isinstance(event, dict):
            out = dict(event)
            out["source"] = "svc-a"
            return out
        return event

    def upper_key(_key: str, event: object) -> object:
        if isinstance(event, dict):
            ev = dict(event)
            if isinstance(ev.get("name"), str):
                ev["name"] = ev["name"].upper()
            return ev
        return event

    stage = StageAdapter(es, stages=(tag_with_source, upper_key))
    for i in range(4):
        stage.publish("orders", {"i": i, "name": f"o{i}"})
    events = list(es.read_from("orders", 0))
    assert [int(e["i"]) for e in events] == [0, 1, 2, 3]  # type: ignore[arg-type]
    assert all(e["source"] == "svc-a" for e in events)  # type: ignore[index]
    assert [e["name"] for e in events] == ["O0", "O1", "O2", "O3"]  # type: ignore[index]


def test_scenario_consumer_resume_after_crash_from_tail() -> None:
    es = InMemoryEventStream()
    for i in range(3):
        es.append("p", {"i": i})

    # Consumer processes everything and remembers tail as its resume point.
    processed: list[int] = []
    for ev in es.read_from("p", 0):
        processed.append(int(ev["i"]))  # type: ignore[arg-type]
    resume = es.tail("p")  # = 4
    assert processed == [0, 1, 2]

    # More events arrive, then consumer restarts at `resume`.
    es.append("p", {"i": 99})
    after_crash = list(es.read_from("p", resume))
    assert after_crash == [{"i": 99}]


def test_scenario_cross_partition_ordering_not_guaranteed() -> None:
    # ES_INV_01 explicitly says cross-partition ordering is NEVER guaranteed.
    # Behaviorally: appending to partition A then partition B gives each its
    # own seq=1; there is no global sequence.
    es = InMemoryEventStream()
    es.append("A", {"x": 1})
    es.append("B", {"x": 2})
    es.append("A", {"x": 3})
    assert es.tail("A") == 3  # 2 events
    assert es.tail("B") == 2  # 1 event
    assert es.partition_size("A") == 2
    assert es.partition_size("B") == 1
