"""Chaos / fault-injection for EventBus.

Game-day scenarios: handlers raising non-Exception subclasses, concurrent
subscribe/unsubscribe/publish races, pathological patterns, and oversized
subscriber fanouts. Bus MUST remain correct under each.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import pytest

from EventBus import EventBusInvariantError, InMemoryEventBus


def test_chaos_handler_raises_base_exception_isolated() -> None:
    bus = InMemoryEventBus()
    survived: list[int] = []

    def bad(n: str, p: Mapping[str, Any]) -> None:
        raise KeyboardInterrupt("synthetic")

    bus.subscribe("c.e", bad)
    bus.subscribe("c.e", lambda n, p: survived.append(1))
    bus.publish("c.e", {})
    assert survived == [1]
    assert bus.errors[0][1] == "KeyboardInterrupt"


def test_chaos_concurrent_subscribe_unsubscribe_publish() -> None:
    bus = InMemoryEventBus()
    errors: list[BaseException] = []

    def subscriber_worker() -> None:
        try:
            for _ in range(200):
                unsub = bus.subscribe("race.x", lambda n, p: None)
                unsub()
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def publisher_worker() -> None:
        try:
            for _ in range(200):
                bus.publish("race.x", {"k": "v"})
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=subscriber_worker) for _ in range(4)]
    threads += [threading.Thread(target=publisher_worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert bus.publish_calls == 800


def test_chaos_malformed_pattern_rejected() -> None:
    bus = InMemoryEventBus()
    for bad in ("", "Bad.Pattern", "a.b.", ".a", "a..b", "a.**.b"):
        with pytest.raises(EventBusInvariantError):
            bus.subscribe(bad, lambda n, p: None)


def test_chaos_malformed_event_name_rejected() -> None:
    bus = InMemoryEventBus()
    for bad in ("noDot", "UPPER.case", "a.b.", "a..b", ""):
        with pytest.raises(EventBusInvariantError):
            bus.publish(bad, {})


def test_chaos_recursive_publish_within_handler() -> None:
    """A handler that publishes to the same bus MUST NOT deadlock.

    We implement this by snapshotting subscribers before dispatch; handlers can
    re-enter publish() freely.
    """
    bus = InMemoryEventBus()
    depth: list[int] = []

    def recursive(n: str, p: Mapping[str, Any]) -> None:
        if len(depth) < 3:
            depth.append(1)
            bus.publish("rec.event", {})

    bus.subscribe("rec.event", recursive)
    bus.publish("rec.event", {})
    assert len(depth) == 3


def test_chaos_many_subscribers_to_same_pattern() -> None:
    bus = InMemoryEventBus()
    hits: list[int] = []
    for _ in range(500):
        bus.subscribe("fan.out", lambda n, p: hits.append(1))
    bus.publish("fan.out", {})
    assert len(hits) == 500


def test_chaos_payload_mutation_attempt_blocked() -> None:
    bus = InMemoryEventBus()
    attempt_errors: list[str] = []

    def sink(event: str, exc: BaseException, payload: Mapping[str, Any]) -> None:
        attempt_errors.append(type(exc).__name__)

    bus = InMemoryEventBus(error_sink=sink)

    def mutator(n: str, p: Mapping[str, Any]) -> None:
        p["injected"] = True  # type: ignore[index] — EVENTBUS-INV-05 forbidden

    bus.subscribe("p.m", mutator)
    bus.publish("p.m", {"k": 1})
    assert "TypeError" in attempt_errors
