"""Unit tests for EventStream — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest

from EventStream import (
    EventStreamInvariantError,
    InMemoryEventStream,
)


# ---------------------------------------------------------------------------
# ES_INV_01 — per-partition strict ordering; cross-partition ordering NOT guaranteed
# ---------------------------------------------------------------------------
def test_inv_per_partition_order_confirms() -> None:
    es = InMemoryEventStream()
    for i in range(5):
        seq = es.append("orders", {"i": i})
        assert seq == i + 1  # per-partition seq starts at 1 and is contiguous
    seqs = [int(e["seq"]) for e in es.log_snapshot("orders")]  # type: ignore[arg-type]
    assert seqs == [1, 2, 3, 4, 5]


def test_inv_per_partition_order_prevents() -> None:
    # Partition key MUST be a non-empty string; ints, bools, empty strings rejected.
    es = InMemoryEventStream()
    for bad in ("", 42, None, True):
        with pytest.raises(EventStreamInvariantError):
            es.append(bad, {"x": 1})  # type: ignore[arg-type]
    # read_from / tail / truncated-of share the same guard.
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("", 0))
    with pytest.raises(EventStreamInvariantError):
        es.tail("")


def test_inv_per_partition_order_under_failure() -> None:
    # Under concurrent appends on the SAME partition, the assigned seqs are
    # strictly monotonic and contiguous (1..N). Cross-partition appends never
    # corrupt the per-partition sequence.
    es = InMemoryEventStream()
    N = 50
    errors: list[BaseException] = []
    lock = threading.Lock()

    def appender(tag: int) -> None:
        try:
            for i in range(N):
                es.append("shared", {"tag": tag, "i": i})
                es.append(f"exclusive_{tag}", {"i": i})
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=appender, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors

    shared = [int(e["seq"]) for e in es.log_snapshot("shared")]  # type: ignore[arg-type]
    assert shared == sorted(shared)
    assert shared == list(range(1, 4 * N + 1))  # contiguous 1..200
    for tag in range(4):
        excl = [int(e["seq"]) for e in es.log_snapshot(f"exclusive_{tag}")]  # type: ignore[arg-type]
        assert excl == list(range(1, N + 1))


# ---------------------------------------------------------------------------
# ES_INV_02 — immutability of appended events
# ---------------------------------------------------------------------------
def test_inv_immutability_confirms() -> None:
    es = InMemoryEventStream()
    payload: dict[str, object] = {"count": 0, "items": [1, 2]}
    es.append("p", payload)
    # Mutate the *caller's* handle — the stored event MUST be unaffected.
    payload["count"] = 999
    items_list = payload["items"]
    if isinstance(items_list, list):
        items_list.append(3)
    snap = es.log_snapshot("p")
    stored = dict(snap[0]["event"])  # type: ignore[arg-type]
    assert stored == {"count": 0, "items": [1, 2]}


def test_inv_immutability_prevents() -> None:
    # Even mutating the iterator's yielded event MUST NOT affect the log.
    es = InMemoryEventStream()
    es.append("p", {"v": 1})
    for ev in es.read_from("p", 0):
        if isinstance(ev, dict):
            ev["v"] = 42  # mutation on the caller-side copy
    # Re-read — original value unchanged.
    again = list(es.read_from("p", 0))
    assert again[0] == {"v": 1}


def test_inv_immutability_under_failure() -> None:
    # Log-snapshot deep-copies: mutating the snapshot list/dict does not leak
    # back into the stored log.
    es = InMemoryEventStream()
    for i in range(3):
        es.append("p", {"i": i})
    snap = es.log_snapshot("p")
    # Try to corrupt the yielded event.
    for entry in snap:
        ev = entry["event"]
        if isinstance(ev, dict):
            ev["i"] = -1
    again = es.log_snapshot("p")
    assert [dict(e["event"]) for e in again] == [{"i": 0}, {"i": 1}, {"i": 2}]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ES_INV_03 — replay / non-destructive consumption
# ---------------------------------------------------------------------------
def test_inv_replay_confirms() -> None:
    es = InMemoryEventStream()
    for i in range(5):
        es.append("p", {"i": i})
    # Consumer A reads everything.
    a = list(es.read_from("p", 0))
    # Consumer B reads everything — same events.
    b = list(es.read_from("p", 0))
    assert a == b == [{"i": i} for i in range(5)]
    # Consumer C resumes from offset 3 (seq >= 3).
    c = list(es.read_from("p", 3))
    assert c == [{"i": 2}, {"i": 3}, {"i": 4}]
    # tail() reports the next-unused seq = 6.
    assert es.tail("p") == 6


def test_inv_replay_prevents() -> None:
    es = InMemoryEventStream()
    es.append("p", {"v": 1})
    # Offset must be a non-negative int (no bools, no strings, no negatives).
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("p", "0"))  # type: ignore[arg-type]
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("p", -1))
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("p", True))  # type: ignore[arg-type]


def test_inv_replay_under_failure() -> None:
    # Reading into a truncated window is REJECTED so consumers never silently
    # lose events that were evicted before their checkpoint.
    es = InMemoryEventStream()
    for i in range(10):
        es.append("p", {"i": i})
    es.truncate_before(5)  # drop seqs 1..4
    # Reading from 5 is fine.
    tail = list(es.read_from("p", 5))
    assert [int(d["i"]) for d in tail] == [4, 5, 6, 7, 8, 9]  # type: ignore[arg-type]
    # Reading from 3 must raise — the reader would see a hole.
    with pytest.raises(EventStreamInvariantError):
        list(es.read_from("p", 3))


# ---------------------------------------------------------------------------
# ES_INV_04 — retention / monotonic truncation
# ---------------------------------------------------------------------------
def test_inv_truncate_retention_confirms() -> None:
    es = InMemoryEventStream(retention_min_entries=2)
    for i in range(5):
        es.append("p", {"i": i})
    # Truncating before seq=3 leaves 3 entries >= retention floor of 2.
    es.truncate_before(3)
    assert es.partition_size("p") == 3
    assert es.truncated_before_of("p") == 3
    # Second truncate advances the cursor monotonically.
    es.truncate_before(4)
    assert es.truncated_before_of("p") == 4
    assert es.partition_size("p") == 2


def test_inv_truncate_retention_prevents() -> None:
    es = InMemoryEventStream(retention_min_entries=2)
    for i in range(5):
        es.append("p", {"i": i})
    es.truncate_before(3)
    # Backdated truncation is REJECTED.
    with pytest.raises(EventStreamInvariantError):
        es.truncate_before(2)
    # Retention-floor violation is REJECTED (would leave < 2 entries).
    with pytest.raises(EventStreamInvariantError):
        es.truncate_before(5)
    # Truncating beyond tail is REJECTED.
    with pytest.raises(EventStreamInvariantError):
        es.truncate_before(999)
    # Negative offset is REJECTED.
    with pytest.raises(EventStreamInvariantError):
        es.truncate_before(-1)


def test_inv_truncate_retention_under_failure() -> None:
    # If truncation would violate retention on ANY partition, NONE are truncated.
    es = InMemoryEventStream(retention_min_entries=3)
    for i in range(10):
        es.append("big", {"i": i})
    for i in range(2):
        es.append("small", {"i": i})
    # truncate_before(2) would leave `small` with 1 entry < floor 3 → rejected.
    with pytest.raises(EventStreamInvariantError):
        es.truncate_before(2)
    # Nothing changed on EITHER partition.
    assert es.partition_size("big") == 10
    assert es.partition_size("small") == 2
    assert es.truncated_before_of("big") == 0
    assert es.truncated_before_of("small") == 0
