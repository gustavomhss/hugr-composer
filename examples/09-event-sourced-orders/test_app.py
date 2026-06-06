"""Tests for the event-sourced orders example."""
from __future__ import annotations

import pytest

from app import (
    EventSourcedStore,
    IdempotentConsumer,
    OutboxRelay,
    fold,
)


def _sample_log(store: EventSourcedStore) -> None:
    store.append("o1", "OrderPlaced", {"items": [1, 2]})
    store.append("o1", "PaymentAuthorized", {"amount": 100})
    store.append("o1", "Shipped", {"carrier": "ups"})
    store.append("o2", "OrderPlaced", {"items": [3]})


def test_fold_is_pure_same_log_same_state() -> None:
    store = EventSourcedStore()
    _sample_log(store)
    log = store.full_log()
    state_a = fold(log)
    state_b = fold(log)
    assert state_a == state_b
    assert state_a["o1"].status == "shipped"
    assert state_a["o2"].status == "placed"


def test_consumer_crash_mid_handler_sees_redelivery() -> None:
    store = EventSourcedStore()
    applied: list[str] = []
    crashed_once = {"flag": True}

    def handler(ev):
        if ev.type == "PaymentAuthorized" and crashed_once["flag"]:
            crashed_once["flag"] = False
            raise RuntimeError("simulated crash")
        applied.append(ev.event_id)

    consumer = IdempotentConsumer(handler)
    relay = OutboxRelay(store)
    relay.subscribe(consumer)
    _sample_log(store)

    # First drain — one handler raises, leaves the event in the failed pile.
    with pytest.raises(RuntimeError):
        relay.drain()
    # "Restart" the consumer: the event is redelivered by ack being partial.
    # Recreate a fresh consumer that sees the outbox from scratch.
    # The outbox still has un-acked events because the handler raised before ack.
    assert len(store.outbox_pending()) >= 1
    # Drain again — succeeds this time.
    relay.drain()
    assert "evt-2" in consumer._applied  # PaymentAuthorized landed


def test_publisher_crash_between_write_and_publish_no_lost_events() -> None:
    store = EventSourcedStore()
    _sample_log(store)
    # Simulate publisher crash AFTER log.append but BEFORE drain.
    assert len(store.outbox_pending()) == 4

    # Restart: relay starts fresh, drains the outbox — no events lost.
    seen: list[str] = []
    consumer = IdempotentConsumer(lambda ev: seen.append(ev.event_id))
    relay = OutboxRelay(store)
    relay.subscribe(consumer)
    delivered = relay.drain()
    assert delivered == 4
    assert len(seen) == 4


def test_replay_from_offset_zero_reconstructs_live_state() -> None:
    store = EventSourcedStore()
    _sample_log(store)
    live = fold(store.full_log())

    replayed_events = store.read_from(offset=0)
    replayed = fold(replayed_events)

    assert live == replayed


def test_idempotent_consumer_ignores_duplicates() -> None:
    store = EventSourcedStore()
    seen: list[str] = []
    consumer = IdempotentConsumer(lambda ev: seen.append(ev.event_id))
    store.append("o1", "OrderPlaced", {})
    ev = store.full_log()[0]
    assert consumer.deliver(ev) is True
    assert consumer.deliver(ev) is False  # redelivery
    assert len(seen) == 1


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
