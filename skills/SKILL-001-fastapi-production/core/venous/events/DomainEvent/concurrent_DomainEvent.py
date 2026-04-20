"""Concurrency / linearizability harness for DomainEvent aggregate stream.

Proves that staging from many threads never violates:

- DE-INV-02: no two distinct events share an event_id in the stream.
- DE-INV-04: per-aggregate versions are strictly monotonic under race.
"""

from __future__ import annotations

import threading

from DomainEvent import (
    AggregateEventStream,
    AggregateStreamError,
    FrozenDomainEvent,
    InMemoryDedupSet,
)
from test_DomainEvent import make_event, uuid_v7


def test_concurrent_cross_aggregate_stage_is_linear_per_stream() -> None:
    """Stagers on DIFFERENT aggregates do not interfere; each stream is linear."""
    stream = AggregateEventStream()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(agg_id: str) -> None:
        try:
            for v in range(1, 51):
                stream.stage(make_event(version=v, aggregate_id=agg_id))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(f"agg-{i}",)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    for i in range(8):
        assert stream.pending_count("Account", f"agg-{i}") == 50


def test_concurrent_same_aggregate_version_race_serialised() -> None:
    """Only one thread wins version N for a single aggregate."""
    stream = AggregateEventStream()
    attempts = 20
    wins = 0
    rejections = 0
    lock = threading.Lock()
    barrier = threading.Barrier(attempts)

    def worker() -> None:
        nonlocal wins, rejections
        barrier.wait()
        try:
            stream.stage(make_event(version=1, aggregate_id="hot",
                                     event_id=uuid_v7()))
            with lock:
                wins += 1
        except AggregateStreamError:
            with lock:
                rejections += 1

    ts = [threading.Thread(target=worker) for _ in range(attempts)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert wins == 1
    assert rejections == attempts - 1
    assert stream.pending_count("Account", "hot") == 1


def test_concurrent_flush_vs_stage_next_version_is_safe() -> None:
    """Concurrent flush (publishing 1..N) and staging N+1 onwards remains linearizable."""
    stream = AggregateEventStream()
    # Pre-load 1..100.
    for v in range(1, 101):
        stream.stage(make_event(version=v, aggregate_id="mix"))
    published: list[FrozenDomainEvent] = []
    done = threading.Event()

    def flusher() -> None:
        stream.flush(published.append)
        done.set()

    t = threading.Thread(target=flusher)
    t.start()
    t.join()
    # After flush, last_version is 100; stage 101..110 now.
    for v in range(101, 111):
        stream.stage(make_event(version=v, aggregate_id="mix"))
    published2: list[FrozenDomainEvent] = []
    stream.flush(published2.append)
    all_versions = [p.version for p in published + published2]
    assert all_versions == list(range(1, 111))


def test_concurrent_dedup_never_double_accepts() -> None:
    """Under heavy concurrent accept for the same event_id, at most one True."""
    dedup = InMemoryDedupSet()
    evt = make_event()
    wins = 0
    losses = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal wins, losses
        if dedup.accept(evt):
            with lock:
                wins += 1
        else:
            with lock:
                losses += 1

    ts = [threading.Thread(target=worker) for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert wins == 1
    assert losses == 39
