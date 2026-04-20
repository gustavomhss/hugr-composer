"""Tests for the exactly-once-on-weak-broker example."""
from __future__ import annotations

import pytest

from app import BrokerEvent, CausalReorderBuffer, IdempotentConsumer


def test_100x_duplicate_deliveries_one_side_effect() -> None:
    effects: list[str] = []
    consumer = IdempotentConsumer(lambda e: effects.append(e.event_id))
    ev = BrokerEvent(event_id="e-1", aggregate_id="a", seq=1, payload={})
    # Deliver 100 duplicates.
    for _ in range(100):
        consumer.deliver(ev)
    assert effects == ["e-1"]


def test_out_of_order_events_delivered_in_causal_order() -> None:
    effects: list[str] = []
    consumer = IdempotentConsumer(lambda e: effects.append(e.event_id))
    buf = CausalReorderBuffer(consumer, gap_timeout_s=5.0)
    e1 = BrokerEvent("e1", "a", 1, {})
    e2 = BrokerEvent("e2", "a", 2, {})
    e3 = BrokerEvent("e3", "a", 3, {})
    # Arrive out of order.
    buf.offer(e3, now=1.0)
    buf.offer(e1, now=1.0)
    buf.offer(e2, now=1.0)
    buf.drain(now=1.0)
    assert effects == ["e1", "e2", "e3"]


def test_stuck_predecessor_times_out_and_records_gap() -> None:
    effects: list[str] = []
    consumer = IdempotentConsumer(lambda e: effects.append(e.event_id))
    buf = CausalReorderBuffer(consumer, gap_timeout_s=5.0)
    # e2 arrives, e1 never comes.
    buf.offer(BrokerEvent("e2", "a", 2, {}), now=0.0)
    # Within timeout — nothing drained.
    assert buf.drain(now=3.0) == 0
    assert effects == []
    # Past timeout — gap recorded, e2 emitted.
    buf.drain(now=10.0)
    assert effects == ["e2"]
    assert len(buf.gaps) == 1 and buf.gaps[0].missing_seq == 1


def test_offset_store_corruption_does_not_replay_landed_effects() -> None:
    effects: list[str] = []
    consumer = IdempotentConsumer(lambda e: effects.append(e.event_id))
    buf = CausalReorderBuffer(consumer)
    e1 = BrokerEvent("e1", "a", 1, {})
    buf.offer(e1, now=0.0)
    buf.drain(now=0.0)
    assert effects == ["e1"]
    # Simulate broker replay: the SAME event comes back.
    consumer.deliver(e1)   # idempotent consumer's dedup catches it
    buf.offer(e1, now=0.1)  # buffer also checks consumer.applied
    buf.drain(now=0.1)
    assert effects == ["e1"]  # no replay


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
