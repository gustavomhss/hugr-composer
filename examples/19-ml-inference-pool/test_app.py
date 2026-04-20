"""Tests for the heterogeneous ML inference pool example."""
from __future__ import annotations

import statistics

import pytest

from app import HeterogeneousWorkerPool, Worker


def _pool() -> HeterogeneousWorkerPool:
    pool = HeterogeneousWorkerPool()
    pool.add(Worker("gpu-1", "gpu", {"llama", "bert"}))
    pool.add(Worker("gpu-2", "gpu", {"llama", "bert"}))
    pool.add(Worker("gpu-3", "gpu", {"llama"}))
    pool.add(Worker("cpu-1", "cpu", {"llama", "bert", "cpu_only_model"}))
    return pool


def test_500_request_burst_stays_within_1_5x_median() -> None:
    pool = _pool()
    # Burst only on GPU-eligible family so routing distributes across 3 GPUs.
    for _ in range(500):
        pool.route(model_family="llama")
    depths = [w.queue_depth for w in pool.snapshot() if w.kind == "gpu"]
    median = statistics.median(depths)
    assert max(depths) <= 1.5 * median, depths


def test_slow_worker_loses_traffic_within_30s() -> None:
    pool = _pool()
    # Baseline: 300 requests — they spread.
    for _ in range(300):
        w = pool.route(model_family="llama")
        pool.complete(w.id)
    # gpu-1 degrades: latency doubles.
    pool.set_latency("gpu-1", 400.0)  # 4× normal
    for w in pool.snapshot():
        pool.complete(w.id)
        # reset queues for a clean before/after window
        w.queue_depth = 0
    # Fresh 100-request window after the regression.
    assigned: dict[str, int] = {}
    for _ in range(100):
        w = pool.route(model_family="llama")
        pool.complete(w.id)
        assigned[w.id] = assigned.get(w.id, 0) + 1
    # gpu-1 should hold ≤ 20% of traffic (losing ≥ 80%).
    assert assigned.get("gpu-1", 0) <= 20, assigned


def test_session_stickiness_and_failover() -> None:
    pool = _pool()
    first = pool.route(model_family="llama", session_id="sess-1")
    second = pool.route(model_family="llama", session_id="sess-1")
    assert first.id == second.id  # sticky
    # The sticky worker dies.
    pool.mark_unhealthy(first.id)
    third = pool.route(model_family="llama", session_id="sess-1")
    assert third.id != first.id  # failover within one request


def test_cpu_only_family_never_routes_to_gpu() -> None:
    pool = _pool()
    for _ in range(20):
        w = pool.route(model_family="cpu_only_model")
        assert w.kind == "cpu"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
