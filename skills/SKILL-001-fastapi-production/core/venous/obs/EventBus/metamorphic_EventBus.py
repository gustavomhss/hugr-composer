"""Metamorphic + differential tests for EventBus.

Algebraic properties:
- unsubscribe idempotency: unsub(), unsub(), ... == unsub() once
- subscription order preserved across publishes
- pattern fan-out distributes over publish (superset rule)
- publish with no matching subscribers is a left identity for delivered_calls
- subscribe/unsubscribe inverse: after balanced calls, no handlers remain
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from EventBus import InMemoryEventBus, pattern_matches


def test_metamorphic_unsubscribe_is_idempotent_n_calls() -> None:
    bus = InMemoryEventBus()
    hits: list[int] = []
    unsub = bus.subscribe("a.b", lambda n, p: hits.append(1))
    for _ in range(100):
        unsub()
    bus.publish("a.b", {})
    assert hits == []


def test_metamorphic_order_is_subscription_order() -> None:
    bus = InMemoryEventBus()
    order: list[int] = []
    for i in range(10):
        bus.subscribe("o.tick", lambda n, p, i=i: order.append(i))
    bus.publish("o.tick", {})
    assert order == list(range(10))


def test_metamorphic_fanout_superset() -> None:
    bus = InMemoryEventBus()
    narrow: list[str] = []
    broad: list[str] = []
    bus.subscribe("x.y", lambda n, p: narrow.append(n))
    bus.subscribe("x.*", lambda n, p: broad.append(n))
    bus.publish("x.y", {})
    bus.publish("x.z", {})
    assert set(narrow).issubset(set(broad))


def test_metamorphic_publish_no_match_zero_delivery() -> None:
    bus = InMemoryEventBus()
    bus.subscribe("http.**", lambda n, p: None)
    bus.publish("sql.query", {})
    assert bus.delivered_calls == 0
    assert bus.publish_calls == 1


def test_metamorphic_subscribe_then_unsubscribe_is_noop() -> None:
    bus = InMemoryEventBus()
    seen: list[int] = []
    unsub = bus.subscribe("k.v", lambda n, p: seen.append(1))
    unsub()
    for _ in range(5):
        bus.publish("k.v", {})
    assert seen == []
    assert bus.subscriber_count == 0


def test_differential_pattern_match_semantics() -> None:
    # '*' matches exactly one segment; '**' matches one-or-more tail segments.
    assert pattern_matches("a.*", "a.b")
    assert not pattern_matches("a.*", "a.b.c")
    assert pattern_matches("a.**", "a.b")
    assert pattern_matches("a.**", "a.b.c.d")
    assert pattern_matches("*.x", "a.x")
    assert not pattern_matches("*.x", "a.b.x")


def test_metamorphic_independent_bus_instances_dont_leak() -> None:
    bus1 = InMemoryEventBus()
    bus2 = InMemoryEventBus()
    hits1: list[int] = []
    hits2: list[int] = []
    bus1.subscribe("q.r", lambda n, p: hits1.append(1))
    bus2.subscribe("q.r", lambda n, p: hits2.append(1))
    bus1.publish("q.r", {})
    assert hits1 == [1]
    assert hits2 == []


def test_metamorphic_payload_snapshot_is_stable() -> None:
    bus = InMemoryEventBus()
    received: list[Mapping[str, Any]] = []
    bus.subscribe("s.n", lambda n, p: received.append(p))
    src = {"k": "v1"}
    bus.publish("s.n", src)
    src["k"] = "v2"  # mutate caller's original AFTER publish
    # The delivered snapshot was frozen at publish time.
    assert received[0]["k"] == "v1"
