"""Tests for HeterogeneousWorkerPool invariants HWP_INV_01..05."""

from __future__ import annotations

import asyncio

import pytest

from core.venous.resiliency.HeterogeneousWorkerPool.HeterogeneousWorkerPool import (
    InMemoryHeterogeneousWorkerPool,
    NoEligibleWorkerError,
    Task,
    WorkerPoolError,
)


def _mk_executor(worker_id: str, latency_s: float = 0.0, records: list[str] | None = None):
    async def exec_(task: Task[object]) -> str:
        if records is not None:
            records.append(worker_id)
        if latency_s:
            await asyncio.sleep(latency_s)
        return f"{worker_id}:{task.payload!r}"

    return exec_


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# INV_01: family gating
# ---------------------------------------------------------------------------
def test_inv_family_gating_confirms() -> None:
    async def scenario() -> None:
        pool = InMemoryHeterogeneousWorkerPool()
        records: list[str] = []
        pool.register("a", frozenset({"llm"}), "gpu", _mk_executor("a", records=records))
        pool.register("b", frozenset({"ocr"}), "cpu", _mk_executor("b", records=records))
        await pool.submit(Task(payload="p"), family="llm")
        assert records == ["a"]

    _run(scenario())


def test_inv_family_gating_prevents_no_worker() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    pool.register("a", frozenset({"llm"}), "gpu", _mk_executor("a"))
    with pytest.raises(NoEligibleWorkerError):
        pool.submit(Task(payload="p"), family="ocr")


# ---------------------------------------------------------------------------
# INV_02: GPU preference
# ---------------------------------------------------------------------------
def test_inv_gpu_preference_confirms() -> None:
    async def scenario() -> None:
        pool = InMemoryHeterogeneousWorkerPool()
        records: list[str] = []
        pool.register("gpu", frozenset({"llm"}), "gpu", _mk_executor("gpu", records=records))
        pool.register("cpu", frozenset({"llm"}), "cpu", _mk_executor("cpu", records=records))
        await pool.submit(Task(payload="p"), family="llm")
        assert records == ["gpu"], "healthy GPU MUST be preferred"

    _run(scenario())


# ---------------------------------------------------------------------------
# INV_03: slow worker deprioritized
# ---------------------------------------------------------------------------
def test_inv_slow_worker_deprioritized_confirms() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    pool.register("slow", frozenset({"llm"}), "gpu", _mk_executor("slow"))
    pool.register("fast", frozenset({"llm"}), "gpu", _mk_executor("fast"))
    # Seed latencies: slow p50 will be 200ms, fast p50 will be 10ms.
    for _ in range(5):
        pool.on_result("fast", 10.0, ok=True)
    for _ in range(5):
        pool.on_result("slow", 200.0, ok=True)
    # Now slow p50 (200) >= 2 * pool p50 (median of mixed set). Slow MUST
    # be marked unhealthy.
    slow = pool._workers["slow"]  # noqa: SLF001
    assert slow.unhealthy_until_ns > 0, "slow worker MUST be deprioritized"


# ---------------------------------------------------------------------------
# INV_04: session stickiness
# ---------------------------------------------------------------------------
def test_inv_session_stickiness_confirms() -> None:
    async def scenario() -> None:
        pool = InMemoryHeterogeneousWorkerPool()
        records: list[str] = []
        pool.register("a", frozenset({"llm"}), "gpu", _mk_executor("a", records=records))
        pool.register("b", frozenset({"llm"}), "gpu", _mk_executor("b", records=records))
        # Force first submission to 'a' by making 'b' look busy.
        pool._workers["b"].queue_depth = 99  # noqa: SLF001
        await pool.submit(Task(payload=1, session_id="S"), family="llm")
        # Even if 'a' is now busier, stickiness MUST keep session on 'a'.
        pool._workers["a"].queue_depth = 99  # noqa: SLF001
        pool._workers["b"].queue_depth = 0  # noqa: SLF001
        await pool.submit(Task(payload=2, session_id="S"), family="llm")
        assert records == ["a", "a"], f"session MUST stick; got {records}"

    _run(scenario())


def test_inv_session_failover_on_unhealthy() -> None:
    async def scenario() -> None:
        pool = InMemoryHeterogeneousWorkerPool()
        records: list[str] = []
        pool.register("a", frozenset({"llm"}), "gpu", _mk_executor("a", records=records))
        pool.register("b", frozenset({"llm"}), "gpu", _mk_executor("b", records=records))
        pool._workers["b"].queue_depth = 99  # noqa: SLF001
        await pool.submit(Task(payload=1, session_id="S"), family="llm")
        # Mark 'a' unhealthy — session MUST fail over to 'b'.
        import time as _t

        pool._workers["a"].unhealthy_until_ns = _t.monotonic_ns() + 60 * 1_000_000_000  # noqa: SLF001
        pool._workers["b"].queue_depth = 0  # noqa: SLF001
        await pool.submit(Task(payload=2, session_id="S"), family="llm")
        assert records == ["a", "b"], f"failover MUST occur; got {records}"

    _run(scenario())


# ---------------------------------------------------------------------------
# INV_05: burst spread
# ---------------------------------------------------------------------------
def test_inv_burst_spread_confirms() -> None:
    async def scenario() -> None:
        pool = InMemoryHeterogeneousWorkerPool()
        for wid in ("a", "b", "c"):
            pool.register(wid, frozenset({"llm"}), "gpu", _mk_executor(wid, latency_s=0.01))
        futs = [pool.submit(Task(payload=i), family="llm") for i in range(30)]
        await asyncio.gather(*futs)
        # After completion queues drain, but at submission time each
        # submit picks the shortest queue. Check at least 2 workers used.
        # We observed workers via executor records — sampled by submit
        # order, the load should roughly round-robin.
        # All three workers MUST have handled at least one task.
        for wid in ("a", "b", "c"):
            assert len(pool._workers[wid].latencies) > 0, f"{wid} never used"  # noqa: SLF001

    _run(scenario())


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_register_rejects_invalid_kind() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    with pytest.raises(WorkerPoolError):
        pool.register("x", frozenset({"llm"}), "tpu", _mk_executor("x"))  # type: ignore[arg-type]


def test_register_rejects_empty_capabilities() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    with pytest.raises(WorkerPoolError):
        pool.register("x", frozenset(), "cpu", _mk_executor("x"))


# ---------------------------------------------------------------------------
# INV_03 rolling p50 deprioritize — weight drops to 0.1× when ratio ≥ 2×
# ---------------------------------------------------------------------------
def test_inv_hwp_inv_03_rolling_p50_deprioritize() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    pool.register("slow", frozenset({"llm"}), "gpu", _mk_executor("slow"))
    pool.register("fast", frozenset({"llm"}), "gpu", _mk_executor("fast"))
    # Seed 100-sample rolling windows: fast p50 = 10ms, slow p50 = 200ms.
    for _ in range(100):
        pool.on_result("fast", 10.0, ok=True)
    for _ in range(100):
        pool.on_result("slow", 200.0, ok=True)
    slow = pool._workers["slow"]  # noqa: SLF001
    fast = pool._workers["fast"]  # noqa: SLF001
    assert slow.weight == pool._DEPRIORITIZED_WEIGHT, (  # noqa: SLF001
        f"slow MUST be deprioritized to 0.1x; got weight={slow.weight}"
    )
    assert slow.unhealthy_until_ns > 0, "slow MUST have a 30s unhealthy window"
    assert fast.weight == 1.0, "healthy worker MUST keep full weight"


# ---------------------------------------------------------------------------
# INV_06 recovery — once p50 normalizes within 1.5× pool p50, full weight back
# ---------------------------------------------------------------------------
def test_inv_hwp_inv_06_recovery() -> None:
    pool = InMemoryHeterogeneousWorkerPool()
    pool.register("w", frozenset({"llm"}), "gpu", _mk_executor("w"))
    pool.register("peer", frozenset({"llm"}), "gpu", _mk_executor("peer"))
    # Phase 1: w looks slow → gets deprioritized.
    for _ in range(100):
        pool.on_result("peer", 10.0, ok=True)
    for _ in range(100):
        pool.on_result("w", 200.0, ok=True)
    w = pool._workers["w"]  # noqa: SLF001
    assert w.weight == pool._DEPRIORITIZED_WEIGHT  # noqa: SLF001

    # Phase 2: w recovers — feed 100 fast samples; rolling deque evicts slow ones.
    for _ in range(100):
        pool.on_result("w", 10.0, ok=True)
    assert w.weight == 1.0, (
        "HWP_INV_06: p50 ratio back under 1.5x pool p50 MUST restore full weight"
    )
    assert w.unhealthy_until_ns == 0, "recovery MUST clear the unhealthy window"
