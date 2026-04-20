"""Unit tests for EventBus — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from EventBus import (
    EventBusInvariantError,
    InMemoryEventBus,
    pattern_matches,
    validate_event_name,
    validate_pattern,
)


# ---------------------------------------------------------------------------
# EVENTBUS_INV_01 — delivery order
# ---------------------------------------------------------------------------
def test_inv_delivery_order_confirms() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []
    bus.subscribe("sql.*", lambda n, p: seen.append(f"a:{n}"))
    bus.subscribe("sql.*", lambda n, p: seen.append(f"b:{n}"))
    bus.subscribe("sql.*", lambda n, p: seen.append(f"c:{n}"))
    bus.publish("sql.query", {"duration": 1})
    assert seen == ["a:sql.query", "b:sql.query", "c:sql.query"]


def test_inv_delivery_order_prevents() -> None:
    bus = InMemoryEventBus()
    # Non-matching patterns MUST NOT be delivered to.
    delivered: list[str] = []
    bus.subscribe("http.*", lambda n, p: delivered.append(n))
    bus.publish("sql.query", {})
    assert delivered == []


def test_inv_delivery_order_under_failure() -> None:
    bus = InMemoryEventBus()
    seen: list[str] = []

    def raiser(n: str, p: Mapping[str, Any]) -> None:
        seen.append("raiser")
        raise RuntimeError("boom")

    bus.subscribe("sql.*", raiser)
    bus.subscribe("sql.*", lambda n, p: seen.append("after"))
    bus.publish("sql.query", {})
    # Both ran, in subscription order, despite raiser's failure.
    assert seen == ["raiser", "after"]


# ---------------------------------------------------------------------------
# EVENTBUS_INV_02 — error isolation
# ---------------------------------------------------------------------------
def test_inv_error_isolation_confirms() -> None:
    reported: list[tuple[str, str, str]] = []

    def sink(event: str, exc: BaseException, payload: Mapping[str, Any]) -> None:
        reported.append((event, type(exc).__name__, str(exc)))

    bus = InMemoryEventBus(error_sink=sink)
    bus.subscribe("x.*", lambda n, p: (_ for _ in ()).throw(ValueError("one")))
    bus.subscribe("x.*", lambda n, p: None)  # survivor
    bus.publish("x.y", {})
    assert len(reported) == 1
    assert reported[0][1] == "ValueError"
    assert bus.delivered_calls == 1  # only the survivor counted


def test_inv_error_isolation_prevents() -> None:
    # A raising sink MUST NOT abort delivery either.
    bus = InMemoryEventBus(
        error_sink=lambda n, e, p: (_ for _ in ()).throw(RuntimeError("sink dead"))
    )
    bus.subscribe("x.y", lambda n, p: (_ for _ in ()).throw(ValueError("h1")))
    survivor_calls: list[int] = []
    bus.subscribe("x.y", lambda n, p: survivor_calls.append(1))
    bus.publish("x.y", {})
    assert survivor_calls == [1]


def test_inv_error_isolation_under_failure() -> None:
    bus = InMemoryEventBus()
    calls: list[str] = []

    def raiser1(n: str, p: Mapping[str, Any]) -> None:
        raise RuntimeError("1")

    def raiser2(n: str, p: Mapping[str, Any]) -> None:
        raise RuntimeError("2")

    bus.subscribe("e.*", raiser1)
    bus.subscribe("e.*", lambda n, p: calls.append("mid"))
    bus.subscribe("e.*", raiser2)
    bus.publish("e.v", {})
    assert calls == ["mid"]
    assert len(bus.errors) == 2


# ---------------------------------------------------------------------------
# EVENTBUS_INV_03 — unsubscribe idempotent
# ---------------------------------------------------------------------------
def test_inv_unsubscribe_idempotent_confirms() -> None:
    bus = InMemoryEventBus()
    hits: list[int] = []
    unsub = bus.subscribe("z.*", lambda n, p: hits.append(1))
    bus.publish("z.t", {})
    unsub()
    unsub()  # second call MUST be a safe no-op
    bus.publish("z.t", {})
    assert hits == [1]


def test_inv_unsubscribe_idempotent_prevents() -> None:
    # Calling an unsub twice MUST NOT remove a different subscription.
    bus = InMemoryEventBus()
    hits_a: list[int] = []
    hits_b: list[int] = []
    unsub_a = bus.subscribe("z.*", lambda n, p: hits_a.append(1))
    bus.subscribe("z.*", lambda n, p: hits_b.append(1))
    unsub_a()
    unsub_a()  # second call: must NOT touch B
    bus.publish("z.q", {})
    assert hits_a == []
    assert hits_b == [1]


def test_inv_unsubscribe_idempotent_under_failure() -> None:
    bus = InMemoryEventBus()
    hits: list[int] = []
    unsub = bus.subscribe("z.*", lambda n, p: hits.append(1))
    for _ in range(50):
        unsub()
    bus.publish("z.q", {})
    assert hits == []
    assert bus.subscriber_count == 0


# ---------------------------------------------------------------------------
# EVENTBUS_INV_04 — naming grammar + pattern syntax
# ---------------------------------------------------------------------------
def test_inv_naming_grammar_confirms() -> None:
    assert validate_event_name("sql.query") == "sql.query"
    assert validate_event_name("sql.active_record") == "sql.active_record"
    assert validate_event_name("db.query.slow") == "db.query.slow"
    assert validate_pattern("sql.*") == "sql.*"
    assert validate_pattern("sql.**") == "sql.**"
    assert validate_pattern("*.active_record") == "*.active_record"
    assert pattern_matches("sql.*", "sql.query")
    assert pattern_matches("sql.**", "sql.query.slow")
    assert not pattern_matches("sql.*", "sql.query.slow")


def test_inv_naming_grammar_prevents() -> None:
    with pytest.raises(EventBusInvariantError):
        validate_event_name("noDotHere")
    with pytest.raises(EventBusInvariantError):
        validate_event_name("UPPER.case")
    with pytest.raises(EventBusInvariantError):
        validate_event_name("")
    with pytest.raises(EventBusInvariantError):
        validate_pattern("sql.**.tail")  # ** only trailing
    with pytest.raises(EventBusInvariantError):
        validate_pattern("sql.$bad")


def test_inv_naming_grammar_under_failure() -> None:
    bus = InMemoryEventBus()
    with pytest.raises(EventBusInvariantError):
        bus.publish("badname", {})
    with pytest.raises(EventBusInvariantError):
        bus.subscribe("bad pattern", lambda n, p: None)


# ---------------------------------------------------------------------------
# EVENTBUS_INV_05 — payload immutability
# ---------------------------------------------------------------------------
def test_inv_payload_immutable_confirms() -> None:
    bus = InMemoryEventBus()
    received: list[Mapping[str, Any]] = []
    bus.subscribe("p.*", lambda n, payload: received.append(payload))
    bus.publish("p.v", {"a": 1, "b": 2})
    assert dict(received[0]) == {"a": 1, "b": 2}
    # The delivered mapping MUST be immutable.
    with pytest.raises(TypeError):
        received[0]["c"] = 3  # type: ignore[index] — EVENTBUS-INV-05 read-only view


def test_inv_payload_immutable_prevents() -> None:
    bus = InMemoryEventBus()
    # Non-Mapping payloads MUST be rejected.
    with pytest.raises(EventBusInvariantError):
        bus.publish("p.v", [1, 2, 3])  # type: ignore[arg-type] — EVENTBUS-INV-05
    with pytest.raises(EventBusInvariantError):
        bus.publish("p.v", "not-a-mapping")  # type: ignore[arg-type] — EVENTBUS-INV-05


def test_inv_payload_immutable_under_failure() -> None:
    # If subscriber A attempts mutation it raises; subscriber B still sees the
    # original payload contents unchanged.
    bus = InMemoryEventBus()
    seen_b: dict[str, Any] = {}

    def mutator(n: str, p: Mapping[str, Any]) -> None:
        # Forbidden — cannot mutate a read-only view.
        p["x"] = 99  # type: ignore[index] — EVENTBUS-INV-05

    def reader(n: str, p: Mapping[str, Any]) -> None:
        seen_b.update(dict(p))

    bus.subscribe("p.*", mutator)
    bus.subscribe("p.*", reader)
    bus.publish("p.v", {"x": 1})
    assert seen_b == {"x": 1}
    assert len(bus.errors) == 1  # mutator's TypeError was reported
