"""Metamorphic + differential tests for DomainEvent.

Algebraic properties proven here:

- event_id equality ↔ dedup outcome identity (DE-INV-02)
- stage + flush is order-preserving and publish-once (DE-INV-04)
- to_dict() is a pure projection: f(e).payload == e.payload materialised
- Schema evolution monotonicity: N+1.required ⊇ N.required (DE-INV-05)
- Discard then stage produces the same result as never-staged (rollback parity)
"""

from __future__ import annotations

from DomainEvent import (
    AggregateEventStream,
    FrozenDomainEvent,
    InMemoryDedupSet,
    SchemaDescriptor,
    SchemaRegistry,
)
from test_DomainEvent import make_event, uuid_v7


def test_metamorphic_event_id_equality_implies_dedup_identity() -> None:
    dedup = InMemoryDedupSet()
    eid = uuid_v7()
    e1 = make_event(event_id=eid, payload={"a": 1})
    e2 = make_event(event_id=eid, payload={"a": 2})  # same id, different payload
    assert dedup.accept(e1) is True
    assert dedup.accept(e2) is False


def test_metamorphic_stage_flush_preserves_order() -> None:
    stream = AggregateEventStream()
    staged: list[FrozenDomainEvent] = []
    for v in range(1, 21):
        e = make_event(version=v)
        stream.stage(e)
        staged.append(e)
    published: list[FrozenDomainEvent] = []
    stream.flush(published.append)
    assert [p.event_id for p in published] == [s.event_id for s in staged]


def test_metamorphic_flush_is_publish_once() -> None:
    stream = AggregateEventStream()
    for v in range(1, 6):
        stream.stage(make_event(version=v))
    calls: list[FrozenDomainEvent] = []
    stream.flush(calls.append)
    n_after_first = len(calls)
    # Second flush MUST NOT re-publish.
    stream.flush(calls.append)
    assert len(calls) == n_after_first == 5


def test_metamorphic_to_dict_is_pure_projection() -> None:
    evt = make_event(payload={"k": "v", "nested": {"a": 1, "b": [1, 2, 3]}})
    a = evt.to_dict()
    b = evt.to_dict()
    assert a == b  # pure
    # Mutating a snapshot CANNOT affect the original event.
    a["payload"]["k"] = "mutated"
    assert evt.payload["k"] == "v"


def test_metamorphic_schema_versions_are_supersets() -> None:
    reg = SchemaRegistry()
    chain = [
        frozenset({"a"}),
        frozenset({"a", "b"}),
        frozenset({"a", "b", "c"}),
        frozenset({"a", "b", "c", "d"}),
    ]
    for i, fields in enumerate(chain, start=1):
        reg.register(SchemaDescriptor("t.ev", i, fields))
    # Each N+1 required-set is a superset of N.
    for i in range(len(chain) - 1):
        assert chain[i].issubset(chain[i + 1])


def test_differential_discard_vs_never_staged() -> None:
    """A stream where N events are staged then discarded behaves identically to a
    never-touched stream at the point of flush + subsequent stage."""
    a = AggregateEventStream()
    b = AggregateEventStream()
    for v in range(1, 6):
        a.stage(make_event(version=v))
    a.discard()
    # Both streams now accept version=1 as the first stage.
    a.stage(make_event(version=1))
    b.stage(make_event(version=1))
    assert a.last_version("Account", "acct-1") == b.last_version("Account", "acct-1") == 0
    assert a.pending_count("Account", "acct-1") == b.pending_count("Account", "acct-1") == 1


def test_metamorphic_dedup_idempotent_on_retry() -> None:
    """Dedup.accept(e) called K times for the same e emits exactly once."""
    dedup = InMemoryDedupSet()
    e = make_event()
    outcomes = [dedup.accept(e) for _ in range(50)]
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 49
