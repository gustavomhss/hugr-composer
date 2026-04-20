"""Behavioral scenarios for MetricMeter."""

from __future__ import annotations

import pytest

from MetricMeter import InMemoryMetricMeter, MetricInvariantError


def test_scenario_http_latency_histogram() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("http.server.duration", unit="ms", description="HTTP latency",
                    boundaries=[1, 5, 10, 50, 100, 500, 1000])
    h.record(34.5, {"http.route": "/checkout", "http.response.status_code": "200"})
    assert len(h._measurements) == 1  # type: ignore[attr-defined]


def test_scenario_counter_rejects_negative() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("checkout.failures", unit="1", description="Failed checkouts")
    with pytest.raises(MetricInvariantError):
        c.add(-5)


def test_scenario_updown_accepts_delta() -> None:
    m = InMemoryMetricMeter()
    u = m.up_down_counter("queue.depth", unit="1", description="Active jobs")
    u.add(5)
    u.add(-3)  # up-down allows negatives


def test_scenario_instrument_name_collision_across_kinds() -> None:
    m = InMemoryMetricMeter()
    m.counter("shared", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        m.histogram("shared", unit="ms", description="d")


def test_scenario_cardinality_guard_blocks_user_id() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("reqs", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        c.add(1, {"user.id": "123"})


def test_scenario_observable_gauge_dropped_on_exception() -> None:
    m = InMemoryMetricMeter()

    def boom() -> float:
        raise RuntimeError("disk full")

    m.observable_gauge("free.bytes", boom, unit="By", description="d")
    assert m.collect_gauge("free.bytes") is None


def test_scenario_histogram_boundaries_immutable() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("h", unit="ms", description="d", boundaries=[1, 5, 25])
    assert h.boundaries == (1.0, 5.0, 25.0)
    with pytest.raises((TypeError, AttributeError)):
        h.boundaries[0] = 999.0  # type: ignore[index]
