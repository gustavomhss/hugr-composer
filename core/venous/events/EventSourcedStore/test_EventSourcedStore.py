"""Unit tests for EventSourcedStore — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from EventSourcedStore import (
    AggregateTypeRegistry,
    ConcurrencyError,
    EventSourcedStoreInvariantError,
    InMemoryEventSourcedStore,
    replay,
    replay_from_snapshot,
)


# ---------------------------------------------------------------------------
# ESS_INV_01 — optimistic concurrency on expected_version
# ---------------------------------------------------------------------------
def test_inv_optimistic_concurrency_confirms() -> None:
    store = InMemoryEventSourcedStore()
    v1 = store.append("agg-1", expected_version=0, events=[{"t": "created"}])
    assert v1 == 1
    v2 = store.append("agg-1", expected_version=1, events=[{"t": "updated"}])
    assert v2 == 2
    assert store.current_version("agg-1") == 2


def test_inv_optimistic_concurrency_prevents() -> None:
    store = InMemoryEventSourcedStore()
    store.append("agg-1", expected_version=0, events=[{"t": "a"}])
    # Second writer thinks version is still 0 → conflict.
    with pytest.raises(ConcurrencyError) as excinfo:
        store.append("agg-1", expected_version=0, events=[{"t": "b"}])
    assert excinfo.value.expected_version == 0
    assert excinfo.value.actual_version == 1
    # All-or-nothing: no event from the rejected batch leaked in.
    assert store.current_version("agg-1") == 1
    assert [e["t"] for e in list(store.load("agg-1"))] == ["a"]


def test_inv_optimistic_concurrency_under_failure() -> None:
    # Under 20 racing threads competing for the same aggregate, EXACTLY one
    # append at expected_version=0 MUST win; the rest MUST raise ConcurrencyError.
    store = InMemoryEventSourcedStore()
    wins: list[int] = []
    losses: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            store.append("agg-race", expected_version=0, events=[{"t": f"e{i}"}])
            with lock:
                wins.append(i)
        except ConcurrencyError as exc:
            with lock:
                losses.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert len(losses) == 19
    assert store.current_version("agg-race") == 1


# ---------------------------------------------------------------------------
# ESS_INV_02 — event immutability
# ---------------------------------------------------------------------------
def test_inv_event_immutability_confirms() -> None:
    store = InMemoryEventSourcedStore()
    store.append("agg-1", expected_version=0, events=[{"amount": 100}])
    loaded = list(store.load("agg-1"))
    assert loaded[0] == {"amount": 100}


def test_inv_event_immutability_prevents() -> None:
    # Mutating the caller's original reference after append MUST NOT affect
    # the stored event, and mutating the loaded copy MUST NOT alter the log.
    store = InMemoryEventSourcedStore()
    original = {"amount": 100}
    store.append("agg-1", expected_version=0, events=[original])
    original["amount"] = 999  # caller mutates their reference
    loaded = list(store.load("agg-1"))
    assert loaded[0] == {"amount": 100}  # stored copy untouched
    loaded[0]["amount"] = -1  # consumer mutates the egress copy
    reloaded = list(store.load("agg-1"))
    assert reloaded[0] == {"amount": 100}  # log still pristine


def test_inv_event_immutability_under_failure() -> None:
    # Any "correction" MUST be a new appended event, not a rewrite. The log
    # grows monotonically; the original event remains visible to audits.
    store = InMemoryEventSourcedStore()
    store.append("agg-1", expected_version=0, events=[{"t": "debit", "n": 10}])
    store.append("agg-1", expected_version=1, events=[{"t": "debit-reversed", "n": 10}])
    events = list(store.load("agg-1"))
    assert len(events) == 2
    assert events[0]["t"] == "debit"
    assert events[1]["t"] == "debit-reversed"


# ---------------------------------------------------------------------------
# ESS_INV_03 — snapshots derivable from the event log
# ---------------------------------------------------------------------------
def _counter_fold(state: object, event: object) -> int:
    base = 0 if state is None else int(state)  # type: ignore[arg-type]  # ESS-INV-04: fold is pure
    assert isinstance(event, dict)
    return base + int(event["delta"])


def test_inv_snapshot_derivable_confirms() -> None:
    store = InMemoryEventSourcedStore()
    for i in range(1, 6):
        store.append("agg-1", expected_version=i - 1, events=[{"delta": i}])
    state, version = replay(store, "agg-1", _counter_fold)
    assert state == 15
    store.snapshot("agg-1", version=version, state=state)
    snap = store.latest_snapshot("agg-1")
    assert snap is not None
    assert snap.version == 5
    assert snap.state == 15


def test_inv_snapshot_derivable_prevents() -> None:
    # Snapshot that out-runs the event log MUST be rejected.
    store = InMemoryEventSourcedStore()
    store.append("agg-1", expected_version=0, events=[{"delta": 1}])
    with pytest.raises(EventSourcedStoreInvariantError):
        store.snapshot("agg-1", version=99, state=999)
    # Re-snapshotting backward MUST be rejected.
    store.snapshot("agg-1", version=1, state=1)
    with pytest.raises(EventSourcedStoreInvariantError):
        store.snapshot("agg-1", version=0, state=0)


def test_inv_snapshot_derivable_under_failure() -> None:
    # Snapshot state mutation by the caller MUST NOT affect what the store
    # returns — the store treats the log as the source of truth, and the
    # snapshot is a cache that MUST remain consistent.
    store = InMemoryEventSourcedStore()
    for i in range(1, 4):
        store.append("agg-1", expected_version=i - 1, events=[{"delta": i}])
    mutable_state: dict[str, int] = {"n": 6}
    store.snapshot("agg-1", version=3, state=mutable_state)
    mutable_state["n"] = -1  # caller mutates ingress reference
    snap = store.latest_snapshot("agg-1")
    assert snap is not None
    assert snap.state == {"n": 6}
    snap.state["n"] = 999  # type: ignore[index]  # ESS-INV-03: egress is a copy
    snap_again = store.latest_snapshot("agg-1")
    assert snap_again is not None
    assert snap_again.state == {"n": 6}


# ---------------------------------------------------------------------------
# ESS_INV_04 — replay determinism
# ---------------------------------------------------------------------------
def test_inv_replay_determinism_confirms() -> None:
    store = InMemoryEventSourcedStore()
    for i in range(1, 11):
        store.append("agg-1", expected_version=i - 1, events=[{"delta": i}])
    a, va = replay(store, "agg-1", _counter_fold)
    b, vb = replay(store, "agg-1", _counter_fold)
    c, vc = replay(store, "agg-1", _counter_fold)
    assert a == b == c == 55
    assert va == vb == vc == 10


def test_inv_replay_determinism_prevents() -> None:
    # Registering the same aggregate type twice would let two teams fold the
    # same log differently — that MUST be rejected.
    reg = AggregateTypeRegistry()
    reg.register("counter", _counter_fold, serializer=lambda e: e)
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.register("counter", _counter_fold, serializer=lambda e: e)


def test_inv_replay_determinism_under_failure() -> None:
    # replay_from_snapshot MUST equal plain replay; taking a snapshot mid-stream
    # MUST NOT change the logical state on the next replay.
    store = InMemoryEventSourcedStore()
    for i in range(1, 8):
        store.append("agg-1", expected_version=i - 1, events=[{"delta": i}])
    mid_state, mid_v = replay(store, "agg-1", _counter_fold)
    store.snapshot("agg-1", version=mid_v, state=mid_state)
    store.append("agg-1", expected_version=mid_v, events=[{"delta": 100}])
    pure, n = replay(store, "agg-1", _counter_fold)
    cached, m = replay_from_snapshot(store, "agg-1", _counter_fold)
    assert pure == cached
    assert n == m == 8
