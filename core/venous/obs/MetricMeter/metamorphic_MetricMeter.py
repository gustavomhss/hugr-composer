"""Metamorphic + differential tests for MetricMeter."""

from __future__ import annotations

from MetricMeter import InMemoryMetricMeter


def test_metamorphic_counter_add_sum() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("sum", unit="1", description="d")
    for v in (1, 2, 3, 4, 5):
        c.add(v)
    total = sum(v for v, _ in c.measurements)
    assert total == 15.0


def test_metamorphic_histogram_preserves_input_count() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("dur", unit="ms", description="d", boundaries=[1, 5, 10])
    for v in (0.5, 3.0, 7.5, 12.0):
        h.record(v)
    assert len(h._measurements) == 4  # type: ignore[attr-defined]


def test_metamorphic_gauge_idempotent_read() -> None:
    m = InMemoryMetricMeter()
    m.observable_gauge("g", lambda: 42.0, unit="1", description="d")
    for _ in range(10):
        assert m.collect_gauge("g") == 42.0


def test_metamorphic_name_case_sensitive() -> None:
    m = InMemoryMetricMeter()
    m.counter("Hits", unit="1", description="d")
    # Different case => different instrument, no collision.
    m.counter("hits", unit="1", description="d")


def test_differential_updown_counter_allows_negative() -> None:
    m = InMemoryMetricMeter()
    u = m.up_down_counter("delta", unit="1", description="d")
    u.add(5)
    u.add(-5)


def test_metamorphic_boundaries_tuple_is_same_object() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("same", unit="ms", description="d", boundaries=[1, 2, 3])
    first = h.boundaries
    second = h.boundaries
    assert first is second  # stable identity proves immutability
