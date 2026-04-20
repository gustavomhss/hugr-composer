"""Behavioral end-to-end scenarios for EventBus — proves invariants at runtime."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from EventBus import InMemoryEventBus


def test_scenario_sql_instrumentation() -> None:
    """Observability provider subscribes to sql.* and records durations."""
    bus = InMemoryEventBus()
    durations: list[int] = []
    bus.subscribe("sql.*", lambda n, p: durations.append(int(p.get("duration", 0))))
    bus.publish("sql.query", {"duration": 12})
    bus.publish("sql.commit", {"duration": 3})
    assert durations == [12, 3]


def test_scenario_hierarchical_wildcard_catches_all() -> None:
    """'db.**' catches db.query, db.query.slow, db.connection.opened, etc."""
    bus = InMemoryEventBus()
    events: list[str] = []
    bus.subscribe("db.**", lambda n, p: events.append(n))
    for name in ("db.query", "db.query.slow", "db.connection.opened"):
        bus.publish(name, {})
    assert events == ["db.query", "db.query.slow", "db.connection.opened"]


def test_scenario_single_segment_wildcard_limits_depth() -> None:
    bus = InMemoryEventBus()
    matched: list[str] = []
    bus.subscribe("sql.*", lambda n, p: matched.append(n))
    bus.publish("sql.query", {})
    bus.publish("sql.query.slow", {})
    assert matched == ["sql.query"]


def test_scenario_multi_provider_dispatch() -> None:
    """Tracing, metrics, and audit each subscribe independently."""
    bus = InMemoryEventBus()
    tracing: list[str] = []
    metrics: list[str] = []
    audit: list[str] = []
    bus.subscribe("http.**", lambda n, p: tracing.append(n))
    bus.subscribe("http.request", lambda n, p: metrics.append(n))
    bus.subscribe("*.audit", lambda n, p: audit.append(n))
    bus.publish("http.request", {"path": "/a"})
    bus.publish("http.request.audit", {"path": "/a"})
    bus.publish("user.audit", {"uid": 1})
    assert tracing == ["http.request", "http.request.audit"]
    assert metrics == ["http.request"]
    assert audit == ["user.audit"]


def test_scenario_unsubscribe_stops_future_delivery() -> None:
    bus = InMemoryEventBus()
    hits: list[int] = []
    unsub = bus.subscribe("z.x", lambda n, p: hits.append(1))
    bus.publish("z.x", {})
    assert hits == [1]
    unsub()
    bus.publish("z.x", {})
    assert hits == [1]
    assert bus.subscriber_count == 0


def test_scenario_broken_subscriber_does_not_break_bus() -> None:
    reports: list[str] = []

    def sink(event: str, exc: BaseException, payload: Mapping[str, Any]) -> None:
        reports.append(f"{event}:{type(exc).__name__}")

    bus = InMemoryEventBus(error_sink=sink)
    survived: list[int] = []
    bus.subscribe("svc.*", lambda n, p: (_ for _ in ()).throw(ValueError("broke")))
    bus.subscribe("svc.*", lambda n, p: survived.append(1))
    for _ in range(5):
        bus.publish("svc.event", {})
    assert survived == [1, 1, 1, 1, 1]
    assert len(reports) == 5


def test_scenario_concurrent_publishers() -> None:
    bus = InMemoryEventBus()
    counter: list[int] = []
    lock = threading.Lock()

    def handler(n: str, p: Mapping[str, Any]) -> None:
        with lock:
            counter.append(1)

    bus.subscribe("load.*", handler)

    def worker() -> None:
        for _ in range(250):
            bus.publish("load.tick", {"x": 1})

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(counter) == 1000


def test_scenario_publish_with_no_subscribers_is_safe() -> None:
    bus = InMemoryEventBus()
    # No-op: MUST NOT raise, MUST count the publish.
    bus.publish("nobody.listens", {"k": "v"})
    assert bus.publish_calls == 1
    assert bus.delivered_calls == 0
