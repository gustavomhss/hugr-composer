"""Unit tests for MetricMeter — confirms/prevents/under_failure per invariant."""

from __future__ import annotations

import pytest

from MetricMeter import (
    InMemoryMetricMeter,
    MetricInvariantError,
    validate_boundaries,
    validate_name,
    validate_unit,
)


# ---------------------------------------------------------------------------
# METRIC_INV_01 — Counter non-negative
# ---------------------------------------------------------------------------
def test_inv_counter_nonneg_confirms() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("req.count", unit="1", description="request count")
    c.add(1)
    c.add(7)


def test_inv_counter_nonneg_prevents() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("c", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        c.add(-1)


def test_inv_counter_nonneg_under_failure() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("c", unit="1", description="d")
    # Repeated negatives MUST continue to raise; no silent clamp after N attempts.
    for _ in range(5):
        with pytest.raises(MetricInvariantError):
            c.add(-0.1)


# ---------------------------------------------------------------------------
# METRIC_INV_02 — Histogram boundaries strict increasing + immutable
# ---------------------------------------------------------------------------
def test_inv_boundaries_strict_confirms() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("lat", unit="ms", description="latency", boundaries=[1.0, 5.0, 25.0, 100.0])
    assert h.boundaries == (1.0, 5.0, 25.0, 100.0)


def test_inv_boundaries_strict_prevents() -> None:
    with pytest.raises(MetricInvariantError):
        validate_boundaries([1.0, 1.0, 5.0])
    with pytest.raises(MetricInvariantError):
        validate_boundaries([float("inf"), 10.0])
    with pytest.raises(MetricInvariantError):
        validate_boundaries([5.0, 3.0, 10.0])


def test_inv_boundaries_strict_under_failure() -> None:
    m = InMemoryMetricMeter()
    h = m.histogram("lat2", unit="ms", description="d", boundaries=[1.0, 10.0])
    # Attempting to mutate boundaries SHALL fail because the tuple is immutable.
    with pytest.raises((TypeError, AttributeError)):
        h.boundaries[0] = 999.0  # type: ignore[index]


# ---------------------------------------------------------------------------
# METRIC_INV_03 — Instrument name + no differently-typed collision
# ---------------------------------------------------------------------------
def test_inv_name_discipline_confirms() -> None:
    validate_name("http.server.request.duration")
    validate_name("db_query")


def test_inv_name_discipline_prevents() -> None:
    with pytest.raises(MetricInvariantError):
        validate_name("1bad")
    with pytest.raises(MetricInvariantError):
        validate_name("has spaces")
    m = InMemoryMetricMeter()
    m.counter("dup", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        m.histogram("dup", unit="ms", description="d")


def test_inv_name_discipline_under_failure() -> None:
    m = InMemoryMetricMeter()
    m.counter("same", unit="1", description="d")
    # Same name, same kind should NOT raise even under repeated creation.
    m.counter("same", unit="1", description="d2")
    # But differently-typed collision remains a failure.
    with pytest.raises(MetricInvariantError):
        m.up_down_counter("same", unit="1", description="d")


# ---------------------------------------------------------------------------
# METRIC_INV_04 — Unit required
# ---------------------------------------------------------------------------
def test_inv_unit_required_confirms() -> None:
    validate_unit("ms")
    validate_unit("s")
    validate_unit("By")


def test_inv_unit_required_prevents() -> None:
    with pytest.raises(MetricInvariantError):
        validate_unit("")
    m = InMemoryMetricMeter()
    with pytest.raises(MetricInvariantError):
        m.counter("c.empty", unit="", description="d")


def test_inv_unit_required_under_failure() -> None:
    m = InMemoryMetricMeter()
    # Even after many successful instruments, empty unit is still rejected.
    for i in range(3):
        m.counter(f"c{i}", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        m.histogram("bad", unit="", description="d")


# ---------------------------------------------------------------------------
# METRIC_INV_05 — Gauge callback SHALL NEVER raise observably
# ---------------------------------------------------------------------------
def test_inv_gauge_safe_confirms() -> None:
    m = InMemoryMetricMeter()
    m.observable_gauge("cpu", lambda: 0.75, unit="1", description="d")
    assert m.collect_gauge("cpu") == 0.75


def test_inv_gauge_safe_prevents() -> None:
    m = InMemoryMetricMeter()

    def bad() -> float:
        raise RuntimeError("callback blew up")

    m.observable_gauge("bad", bad, unit="1", description="d")
    # Invariant: exception is logged + measurement dropped; collector returns None.
    assert m.collect_gauge("bad") is None


def test_inv_gauge_safe_under_failure() -> None:
    m = InMemoryMetricMeter()
    counter = {"n": 0}

    def flaky() -> float:
        counter["n"] += 1
        if counter["n"] % 2 == 0:
            raise ValueError("intermittent")
        return 1.0

    m.observable_gauge("flaky", flaky, unit="1", description="d")
    results = [m.collect_gauge("flaky") for _ in range(10)]
    # Half should be 1.0, half None; never a raised exception.
    assert results.count(1.0) == 5
    assert results.count(None) == 5


# ---------------------------------------------------------------------------
# METRIC_INV_06 — Forbidden cardinality keys
# ---------------------------------------------------------------------------
def test_inv_cardinality_keys_confirms() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("safe", unit="1", description="d")
    c.add(1, {"http.route": "/checkout", "http.response.status_code": "200"})


def test_inv_cardinality_keys_prevents() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("dangerous", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        c.add(1, {"user.id": "u-123"})
    with pytest.raises(MetricInvariantError):
        c.add(1, {"request.id": "r-456"})


def test_inv_cardinality_keys_under_failure() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("d", unit="1", description="d")
    for forbidden in ("user.id", "request.id", "http.url", "trace_id"):
        with pytest.raises(MetricInvariantError):
            c.add(1, {forbidden: "x"})
