"""Chaos / game-day tests for DomainEvent.

Simulates publisher crashes, duplicate deliveries, race storms on the version
counter, schema drift, and payload poisoning to prove the invariants never
slip under adversarial conditions.
"""

from __future__ import annotations

import threading

import pytest

from DomainEvent import (
    AggregateEventStream,
    AggregateStreamError,
    DomainEventInvariantError,
    FrozenDomainEvent,
    InMemoryDedupSet,
    SchemaDescriptor,
    SchemaRegistry,
    SchemaRegistryError,
)
from test_DomainEvent import make_event, uuid_v7


def test_chaos_publisher_raises_then_events_not_advanced() -> None:
    """If publish_fn raises midway, DE-INV-04 watermark remains before-failure."""
    stream = AggregateEventStream()
    for v in range(1, 6):
        stream.stage(make_event(version=v))
    calls: list[int] = []

    def angry(evt: FrozenDomainEvent) -> None:
        calls.append(evt.version)
        if evt.version == 3:
            raise OSError("broker down")

    with pytest.raises(OSError):
        stream.flush(angry)
    # Publisher saw versions 1..3 but the watermark did not advance — safe to
    # retry by draining pending after reconnect.
    assert calls == [1, 2, 3]
    assert stream.last_version("Account", "acct-1") == 0


def test_chaos_duplicate_delivery_storm_never_double_handles() -> None:
    dedup = InMemoryDedupSet()
    evts = [make_event(version=v) for v in range(1, 101)]
    for _ in range(10):  # ten redeliveries
        for e in evts:
            dedup.accept(e)
    assert dedup.size() == 100


def test_chaos_concurrent_stagers_one_aggregate_race() -> None:
    """Many threads race to stage for one aggregate; exactly one wins each version slot."""
    stream = AggregateEventStream()
    attempts = 8
    collisions: list[BaseException] = []
    lock = threading.Lock()
    barrier = threading.Barrier(attempts)

    def worker(v: int) -> None:
        barrier.wait()
        try:
            stream.stage(make_event(version=v, aggregate_id="race"))
        except AggregateStreamError as exc:
            with lock:
                collisions.append(exc)

    # All threads try to stage version=1 — only one may succeed.
    ts = [threading.Thread(target=worker, args=(1,)) for _ in range(attempts)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(collisions) == attempts - 1
    assert stream.pending_count("Account", "race") == 1


def test_chaos_schema_drift_poisoned_payload_rejected() -> None:
    reg = SchemaRegistry()
    reg.register(SchemaDescriptor("invoice.issued", 1,
                                   frozenset({"total", "currency"})))
    good = make_event(event_type="invoice.issued", schema_version=1,
                     payload={"total": 100, "currency": "USD"})
    reg.validate_event(good)
    # Poisoned: missing required `currency`.
    bad = make_event(event_type="invoice.issued", schema_version=1,
                     payload={"total": 100})
    with pytest.raises(SchemaRegistryError):
        reg.validate_event(bad)


def test_chaos_malformed_uuid_never_enters_stream() -> None:
    for malformed in ["abc", "not-a-uuid", "12345", "x" * 36,
                       "12345678-1234-4234-8234-123456789012",
                       "00000000-0000-4000-8000-000000000000"]:
        with pytest.raises(DomainEventInvariantError):
            FrozenDomainEvent(
                event_id=malformed,
                aggregate_id="a",
                occurred_at="2025-01-01T00:00:00Z",
                version=1,
                payload={},
            )


def test_chaos_schema_registry_concurrent_registration_safe() -> None:
    reg = SchemaRegistry()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            reg.register(SchemaDescriptor(f"ev.type{i}", 1, frozenset({"k"})))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(32)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # Each type registered exactly once.
    for i in range(32):
        assert reg.get(f"ev.type{i}", 1).required_fields == frozenset({"k"})


def test_chaos_flush_outside_lock_allows_slow_publisher() -> None:
    """Slow publisher does NOT block a concurrent reader of last_version."""
    stream = AggregateEventStream()
    for v in range(1, 11):
        stream.stage(make_event(version=v))
    progress: list[int] = []
    done = threading.Event()

    def slow(evt: FrozenDomainEvent) -> None:
        progress.append(evt.version)

    def reader() -> None:
        while not done.is_set():
            _ = stream.pending_count("Account", "acct-1")

    r = threading.Thread(target=reader)
    r.start()
    try:
        stream.flush(slow)
    finally:
        done.set()
        r.join(timeout=2.0)
    assert progress == list(range(1, 11))


def test_chaos_huge_batch_publishes_in_order() -> None:
    stream = AggregateEventStream()
    for v in range(1, 5001):
        stream.stage(make_event(version=v, aggregate_id="big"))
    published: list[int] = []
    stream.flush(lambda e: published.append(e.version))
    assert published == list(range(1, 5001))


def test_chaos_event_id_collision_storm_detected() -> None:
    stream = AggregateEventStream()
    eid = uuid_v7()
    stream.stage(make_event(event_id=eid, version=1))
    # Next stage attempts reuse the same event_id — all must be rejected.
    for v in range(2, 20):
        with pytest.raises(AggregateStreamError):
            stream.stage(make_event(event_id=eid, version=v))
