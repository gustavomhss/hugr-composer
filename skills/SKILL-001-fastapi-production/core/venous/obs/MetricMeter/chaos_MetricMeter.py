"""Chaos tests for MetricMeter."""

from __future__ import annotations

import threading

import pytest

from MetricMeter import InMemoryMetricMeter, MetricInvariantError


def test_chaos_concurrent_counter_add() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("race", unit="1", description="d")

    def worker() -> None:
        for _ in range(100):
            c.add(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(v for v, _ in c.measurements) == 800.0


def test_chaos_repeated_invalid_name_never_leaks() -> None:
    m = InMemoryMetricMeter()
    for bad in ("", " ", "1start", "bad name", "a" * 100):
        with pytest.raises(MetricInvariantError):
            m.counter(bad, unit="1", description="d")
    # After many failures a valid instrument still works.
    c = m.counter("ok", unit="1", description="d")
    c.add(1)


def test_chaos_negative_counter_after_positives_still_rejected() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("c", unit="1", description="d")
    for _ in range(50):
        c.add(1)
    with pytest.raises(MetricInvariantError):
        c.add(-1)


def test_chaos_histogram_with_nan_rejected() -> None:
    m = InMemoryMetricMeter()
    with pytest.raises(MetricInvariantError):
        m.histogram("nan", unit="ms", description="d", boundaries=[float("nan"), 1])


def test_chaos_gauge_long_running_exceptions_do_not_leak() -> None:
    m = InMemoryMetricMeter()
    n = {"i": 0}

    def unstable() -> float:
        n["i"] += 1
        if n["i"] > 100:
            raise RuntimeError("disk full")
        return 1.0

    m.observable_gauge("g", unstable, unit="1", description="d")
    for _ in range(200):
        m.collect_gauge("g")


def test_chaos_forbidden_key_not_bypassed_by_extra_keys() -> None:
    m = InMemoryMetricMeter()
    c = m.counter("c", unit="1", description="d")
    with pytest.raises(MetricInvariantError):
        c.add(1, {"http.route": "/ok", "user.id": "123"})


def test_chaos_many_boundaries_handled() -> None:
    m = InMemoryMetricMeter()
    bounds = list(range(1, 21))
    h = m.histogram("many", unit="ms", description="d", boundaries=bounds)
    assert len(h.boundaries) == 20
