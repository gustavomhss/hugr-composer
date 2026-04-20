"""Metamorphic + differential tests for EventSourcedStore.

Algebraic / differential laws:

- L1 (replay is pure):     replay(log) == replay(log)                 (ESS-INV-04)
- L2 (append-load chain):  load_after_append == prior_load + appended (ESS-INV-02 + 04)
- L3 (snapshot parity):    replay_from_snapshot == pure replay        (ESS-INV-03)
- L4 (version monotone):   v(append(v)) == v + len(batch)             (ESS-INV-01)
- L5 (ingress immutability): caller-side mutation of originals doesn't leak
- L6 (batch decomposition): one append of N events ≡ N appends of 1 event
  (for the resulting state via replay)                                (ESS-INV-04)
"""

from __future__ import annotations

from EventSourcedStore import (
    InMemoryEventSourcedStore,
    replay,
    replay_from_snapshot,
)


def _sum_fold(state: object, event: object) -> int:
    assert isinstance(event, dict)
    base = 0 if state is None else int(state)  # type: ignore[arg-type]
    return base + int(event["n"])


def test_metamorphic_replay_is_pure() -> None:
    # L1
    store = InMemoryEventSourcedStore()
    for i in range(1, 11):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    results = [replay(store, "a", _sum_fold) for _ in range(20)]
    assert len({r[0] for r in results}) == 1
    assert results[0][0] == 55


def test_metamorphic_append_load_chain() -> None:
    # L2
    store = InMemoryEventSourcedStore()
    store.append("a", expected_version=0, events=[{"n": 1}])
    prior = [e["n"] for e in list(store.load("a"))]
    store.append("a", expected_version=1, events=[{"n": 2}, {"n": 3}])
    after = [e["n"] for e in list(store.load("a"))]
    assert after == prior + [2, 3]


def test_metamorphic_snapshot_parity() -> None:
    # L3
    store = InMemoryEventSourcedStore()
    for i in range(1, 21):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    mid_state, mid_v = replay(store, "a", _sum_fold)
    store.snapshot("a", version=mid_v, state=mid_state)
    for i in range(21, 26):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    pure_state, pure_v = replay(store, "a", _sum_fold)
    cached_state, cached_v = replay_from_snapshot(store, "a", _sum_fold)
    assert pure_state == cached_state
    assert pure_v == cached_v


def test_metamorphic_version_monotone_by_batch_size() -> None:
    # L4
    store = InMemoryEventSourcedStore()
    batch = [{"n": i} for i in range(5)]
    before = store.current_version("a")
    after = store.append("a", expected_version=before, events=batch)
    assert after == before + len(batch)


def test_metamorphic_ingress_immutability() -> None:
    # L5
    store = InMemoryEventSourcedStore()
    events = [{"n": 1}, {"n": 2}]
    store.append("a", expected_version=0, events=events)
    events[0]["n"] = -100
    events[1]["n"] = -200
    loaded = [e["n"] for e in list(store.load("a"))]
    assert loaded == [1, 2]


def test_differential_batch_decomposition_equals_single_appends() -> None:
    # L6
    store_batch = InMemoryEventSourcedStore()
    store_single = InMemoryEventSourcedStore()
    events = [{"n": i} for i in range(1, 8)]
    store_batch.append("x", expected_version=0, events=events)
    for i, e in enumerate(events):
        store_single.append("x", expected_version=i, events=[e])
    s_batch, v_batch = replay(store_batch, "x", _sum_fold)
    s_single, v_single = replay(store_single, "x", _sum_fold)
    assert s_batch == s_single == sum(range(1, 8))
    assert v_batch == v_single == 7


def test_differential_two_stores_agree_on_replay() -> None:
    # Same sequence of appends into two independent stores MUST yield the
    # same replay (ESS-INV-04 — determinism is a property of the log, not the
    # store instance).
    a = InMemoryEventSourcedStore()
    b = InMemoryEventSourcedStore()
    script = [{"n": i * 2 + 1} for i in range(15)]
    for i, e in enumerate(script):
        a.append("k", expected_version=i, events=[e])
        b.append("k", expected_version=i, events=[e])
    sa, _ = replay(a, "k", _sum_fold)
    sb, _ = replay(b, "k", _sum_fold)
    assert sa == sb


def test_metamorphic_load_is_snapshot_not_live_iterator() -> None:
    # Consumers iterating a load result MUST NOT observe events appended after
    # load() was called — the returned iterator is a snapshot of the log at
    # load time. This supports ESS-INV-04 (determinism of replay).
    store = InMemoryEventSourcedStore()
    store.append("k", expected_version=0, events=[{"n": 1}])
    it = iter(store.load("k"))
    store.append("k", expected_version=1, events=[{"n": 2}])
    yielded = list(it)
    assert [e["n"] for e in yielded] == [1]
