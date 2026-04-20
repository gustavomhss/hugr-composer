"""Chaos / game-day tests for EventSourcedStore.

Fault-injection suite: concurrency conflicts under load, enormous batches,
invalid snapshots, malformed inputs, registry collisions — the store must
never enter an inconsistent state.
"""

from __future__ import annotations

import threading

import pytest

from EventSourcedStore import (
    AggregateTypeRegistry,
    ConcurrencyError,
    EventSourcedStoreInvariantError,
    InMemoryEventSourcedStore,
    replay,
)


def _fold(state: object, event: object) -> int:
    assert isinstance(event, dict)
    base = 0 if state is None else int(state)  # type: ignore[arg-type]
    return base + int(event.get("n", 0))


def test_chaos_storm_of_concurrent_appenders_single_winner() -> None:
    store = InMemoryEventSourcedStore()
    wins: list[int] = []
    losses: list[int] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            store.append("a", expected_version=0, events=[{"n": 1}])
            with lock:
                wins.append(1)
        except ConcurrencyError:
            with lock:
                losses.append(1)

    threads = [threading.Thread(target=worker) for _ in range(64)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert len(wins) + len(losses) == 64
    assert store.current_version("a") == 1


def test_chaos_huge_batch_append_atomic() -> None:
    store = InMemoryEventSourcedStore()
    batch = [{"n": 1} for _ in range(10_000)]
    v = store.append("big", expected_version=0, events=batch)
    assert v == 10_000
    state, _ = replay(store, "big", _fold)
    assert state == 10_000


def test_chaos_empty_batch_is_noop() -> None:
    store = InMemoryEventSourcedStore()
    v = store.append("a", expected_version=0, events=[])
    assert v == 0
    assert store.current_version("a") == 0


def test_chaos_malformed_expected_version_rejected() -> None:
    store = InMemoryEventSourcedStore()
    with pytest.raises(EventSourcedStoreInvariantError):
        store.append("a", expected_version="0", events=[{"n": 1}])  # type: ignore[arg-type]  # ESS-INV-01
    with pytest.raises(EventSourcedStoreInvariantError):
        store.append("a", expected_version=True, events=[{"n": 1}])  # type: ignore[arg-type]  # ESS-INV-01
    with pytest.raises(EventSourcedStoreInvariantError):
        store.append("a", expected_version=-1, events=[{"n": 1}])


def test_chaos_empty_aggregate_id_rejected() -> None:
    store = InMemoryEventSourcedStore()
    with pytest.raises(EventSourcedStoreInvariantError):
        store.append("", expected_version=0, events=[{"n": 1}])
    with pytest.raises(EventSourcedStoreInvariantError):
        list(store.load(""))
    with pytest.raises(EventSourcedStoreInvariantError):
        store.snapshot("", version=0, state={})


def test_chaos_snapshot_cannot_outrun_log() -> None:
    store = InMemoryEventSourcedStore()
    store.append("a", expected_version=0, events=[{"n": 1}])
    with pytest.raises(EventSourcedStoreInvariantError):
        store.snapshot("a", version=99, state=9999)


def test_chaos_snapshot_cannot_rewind() -> None:
    store = InMemoryEventSourcedStore()
    for i in range(1, 6):
        store.append("a", expected_version=i - 1, events=[{"n": i}])
    store.snapshot("a", version=5, state=15)
    with pytest.raises(EventSourcedStoreInvariantError):
        store.snapshot("a", version=3, state=6)


def test_chaos_registry_double_registration_rejected() -> None:
    reg = AggregateTypeRegistry()
    reg.register("counter", _fold, serializer=lambda e: e)
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.register("counter", _fold, serializer=lambda e: e)
    # Unknown lookups fail loudly.
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.fold_for("missing")
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.serializer_for("missing")


def test_chaos_registry_non_callable_rejected() -> None:
    reg = AggregateTypeRegistry()
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.register("x", "not-callable", serializer=lambda e: e)  # type: ignore[arg-type]  # ESS-INV-04
    with pytest.raises(EventSourcedStoreInvariantError):
        reg.register("x", _fold, serializer=42)  # type: ignore[arg-type]  # ESS-INV-04


def test_chaos_many_aggregates_isolated() -> None:
    # Appends on aggregate-A MUST NOT leak into aggregate-B's version.
    store = InMemoryEventSourcedStore()
    for i in range(1, 11):
        store.append("A", expected_version=i - 1, events=[{"n": i}])
    assert store.current_version("B") == 0
    store.append("B", expected_version=0, events=[{"n": 100}])
    assert store.current_version("A") == 10
    assert store.current_version("B") == 1


def test_chaos_concurrent_mixed_aggregates() -> None:
    # 8 aggregates, 16 workers each — every aggregate ends at exactly 16.
    store = InMemoryEventSourcedStore()
    retries_per_agg = 16
    aggregates = [f"agg-{i}" for i in range(8)]
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(agg: str) -> None:
        try:
            while True:
                v = store.current_version(agg)
                try:
                    store.append(agg, expected_version=v, events=[{"n": 1}])
                    return
                except ConcurrencyError:
                    continue
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads: list[threading.Thread] = []
    for agg in aggregates:
        for _ in range(retries_per_agg):
            threads.append(threading.Thread(target=worker, args=(agg,)))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    for agg in aggregates:
        assert store.current_version(agg) == retries_per_agg
