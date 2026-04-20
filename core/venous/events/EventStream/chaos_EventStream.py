"""Chaos / game-day tests for EventStream.

Simulates:
- producer crash mid-publish (stage raises) → no torn writes (ES-INV-02);
- malformed append flood → every malformed input rejected, log unchanged;
- truncate rewind flood → every attempt rejected, cursor holds (ES-INV-04);
- reader-into-hole flood → every attempt rejected (ES-INV-03);
- schema-less massive burst (10_000 appends) → per-partition seqs 1..N;
- mutation-after-append attack → stored events unchanged (ES-INV-02).
"""

from __future__ import annotations

import pytest

from EventStream import (
    EventStreamInvariantError,
    InMemoryEventStream,
    StageAdapter,
)


def test_chaos_stage_exception_does_not_corrupt_log() -> None:
    es = InMemoryEventStream()

    def exploder(_key: str, _ev: object) -> object:
        raise RuntimeError("stage blew up")

    stage = StageAdapter(es, stages=(exploder,))
    with pytest.raises(RuntimeError):
        stage.publish("p", {"v": 1})
    # The event never reached the downstream append — log stays empty.
    assert es.partition_size("p") == 0
    assert es.tail("p") == 1


def test_chaos_malformed_append_flood_rejected() -> None:
    es = InMemoryEventStream()
    for bad in ("", None, 42, b"bytes", ("tup",), [1, 2]):
        with pytest.raises(EventStreamInvariantError):
            es.append(bad, {"v": 1})  # type: ignore[arg-type]
    # Nothing landed on any partition.
    assert es.partition_count == 0


def test_chaos_truncate_rewind_flood_rejected() -> None:
    es = InMemoryEventStream(retention_min_entries=0)
    for i in range(10):
        es.append("p", {"i": i})
    es.truncate_before(5)
    for i in range(5):
        with pytest.raises(EventStreamInvariantError):
            es.truncate_before(i)
    assert es.truncated_before_of("p") == 5


def test_chaos_reader_into_hole_always_rejected() -> None:
    es = InMemoryEventStream(retention_min_entries=0)
    for i in range(5):
        es.append("p", {"i": i})
    es.truncate_before(3)
    for bad in (0, 1, 2):
        with pytest.raises(EventStreamInvariantError):
            list(es.read_from("p", bad))
    # Valid reads still work.
    tail = list(es.read_from("p", 3))
    assert len(tail) == 3  # seqs 3, 4, 5


def test_chaos_massive_burst_single_partition() -> None:
    es = InMemoryEventStream()
    N = 10_000
    for i in range(N):
        es.append("p", {"i": i})
    assert es.tail("p") == N + 1
    assert es.partition_size("p") == N
    # First and last seqs are 1 and N.
    snap = es.log_snapshot("p")
    assert int(snap[0]["seq"]) == 1  # type: ignore[arg-type]
    assert int(snap[-1]["seq"]) == N  # type: ignore[arg-type]


def test_chaos_caller_mutation_after_append_does_not_corrupt() -> None:
    # ES-INV-02: a malicious/buggy caller who mutates the payload AFTER
    # appending MUST NOT be able to corrupt the stored entry.
    es = InMemoryEventStream()
    payload: dict[str, object] = {"x": [1, 2, 3], "nested": {"k": "v"}}
    es.append("p", payload)
    # Now torch the caller's copy.
    x_list = payload["x"]
    if isinstance(x_list, list):
        x_list.clear()
        x_list.append(99)
    nested = payload["nested"]
    if isinstance(nested, dict):
        nested["k"] = "mutated"
    payload["new_field"] = "added"
    # Stored event is intact.
    snap = es.log_snapshot("p")
    stored_event = snap[0]["event"]
    assert stored_event == {"x": [1, 2, 3], "nested": {"k": "v"}}


def test_chaos_partition_cap_enforced() -> None:
    es = InMemoryEventStream()
    # Create many distinct partitions up to the cap.
    # Use a small proxy: the cap is 10_000; we verify the guard fires by
    # monkey-patching via subclass.
    class TinyCap(InMemoryEventStream):
        _MAX_PARTITIONS = 3

    es2 = TinyCap()
    for i in range(3):
        es2.append(f"p{i}", {"i": i})
    with pytest.raises(EventStreamInvariantError):
        es2.append("p-over", {"i": 4})


def test_chaos_read_unknown_partition_is_empty_not_error() -> None:
    # Routine polling of a partition that has not yet seen its first event is
    # a normal read → returns an empty iterator instead of raising.
    es = InMemoryEventStream()
    assert list(es.read_from("unknown", 0)) == []
    assert es.tail("unknown") == 1
    assert es.partition_size("unknown") == 0
