"""Behavioral end-to-end scenarios for DomainEvent — proves invariants at runtime.

Each scenario models a realistic aggregate workflow:

- Pre-commit collection → post-commit publish (outbox-style)
- Idempotent consumer using event_id dedup
- Rollback discards staged events without publishing
- Cross-aggregate concurrent publishing
- Additive schema evolution allowing old + new consumers to coexist
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


def test_scenario_pre_commit_collect_post_commit_publish() -> None:
    """Canonical DDD outbox flow: events collected before commit, published after."""
    stream = AggregateEventStream()
    published: list[FrozenDomainEvent] = []

    # Unit of work — stages three facts about one aggregate.
    stream.stage(make_event(version=1, event_type="account.opened",
                            payload={"currency": "USD"}))
    stream.stage(make_event(version=2, event_type="account.funded",
                            payload={"amount": 100}))
    stream.stage(make_event(version=3, event_type="account.funded",
                            payload={"amount": 50}))

    # Before commit, nothing is published.
    assert published == []
    # "Commit succeeded" → flush publishes in staged order.
    stream.flush(published.append)
    assert [e.version for e in published] == [1, 2, 3]
    assert stream.pending_count("Account", "acct-1") == 0


def test_scenario_idempotent_consumer_dedups_on_event_id() -> None:
    """Downstream consumer sees each event at most once via event_id."""
    dedup = InMemoryDedupSet()
    evt = make_event()
    delivered_count = 0
    for _ in range(10):  # at-least-once delivery
        if dedup.accept(evt):
            delivered_count += 1
    assert delivered_count == 1


def test_scenario_rollback_discards_without_publish() -> None:
    """Rollback MUST NOT publish any staged event (DE-INV-01 adjacent + DE-INV-04)."""
    stream = AggregateEventStream()
    for v in range(1, 6):
        stream.stage(make_event(version=v))
    stream.discard()
    published: list[FrozenDomainEvent] = []
    stream.flush(published.append)
    assert published == []
    assert stream.last_version("Account", "acct-1") == 0


def test_scenario_concurrent_cross_aggregate_streams_preserve_ordering() -> None:
    """Independent aggregates stream their versions concurrently without interference."""
    stream = AggregateEventStream()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(agg_id: str) -> None:
        try:
            for v in range(1, 21):
                stream.stage(make_event(version=v, aggregate_id=agg_id))
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(f"acct-{i}",)) for i in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    published: list[FrozenDomainEvent] = []
    stream.flush(published.append)
    # Every aggregate emitted versions 1..20 contiguously.
    per_agg: dict[str, list[int]] = {}
    for e in published:
        per_agg.setdefault(e.aggregate_id, []).append(e.version)
    for agg_id, versions in per_agg.items():
        assert versions == list(range(1, 21)), f"aggregate {agg_id}: {versions}"


def test_scenario_additive_schema_evolution_backward_compatible() -> None:
    """v1 consumers and v2 consumers BOTH read the event; removed fields are forbidden."""
    reg = SchemaRegistry()
    reg.register(SchemaDescriptor("order.placed", 1, frozenset({"sku", "qty"})))
    reg.register(
        SchemaDescriptor("order.placed", 2, frozenset({"sku", "qty", "currency"})),
    )
    v1 = make_event(event_type="order.placed", schema_version=1,
                    payload={"sku": "A", "qty": 2})
    v2 = make_event(event_type="order.placed", schema_version=2,
                    payload={"sku": "B", "qty": 1, "currency": "USD"})
    reg.validate_event(v1)
    reg.validate_event(v2)
    # Removal in v3 MUST be rejected.
    with pytest.raises(SchemaRegistryError):
        reg.register(SchemaDescriptor("order.placed", 3, frozenset({"sku"})))


def test_scenario_fact_only_event_type_enforced_at_publish() -> None:
    """Imperative event_types NEVER reach the stream (DE-INV-03)."""
    with pytest.raises(DomainEventInvariantError):
        make_event(event_type="order.place")


def test_scenario_event_serialisation_is_pure_read() -> None:
    """to_dict() snapshot CANNOT mutate the source event (DE-INV-01)."""
    evt = make_event(payload={"amount": 100, "tags": ["x", "y"]})
    snap = evt.to_dict()
    snap["payload"]["amount"] = 999
    # snap mutation does not leak back into the frozen event.
    assert evt.payload["amount"] == 100


def test_scenario_retroactive_insert_rejected() -> None:
    """Once version N is staged, version N-1 CANNOT be staged afterwards (DE-INV-04)."""
    stream = AggregateEventStream()
    stream.stage(make_event(version=1))
    stream.stage(make_event(version=2))
    with pytest.raises(AggregateStreamError):
        stream.stage(make_event(version=1, event_id=uuid_v7()))
