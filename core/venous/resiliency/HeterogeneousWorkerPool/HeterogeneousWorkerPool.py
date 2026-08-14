"""HeterogeneousWorkerPool primitive — mixed CPU+GPU inference routing.

Routes ``submit(task, family)`` across a set of registered workers with
different capabilities and a pool-level view of per-worker rolling p50
latency and queue depth. GPU workers are preferred when healthy;
unhealthy workers are deprioritized; sessions are sticky until a worker
unhealthies.

Framework-agnostic: pure stdlib + asyncio. No Ray import. The OSS
reference is cited in ``HeterogeneousWorkerPool.md`` provenance.

Invariant IDs (full text in ``HeterogeneousWorkerPool.md``):

- HWP_INV_01: A task with ``family=F`` MUST land on a worker advertising
  F in its capabilities.
- HWP_INV_02: GPU workers preferred when any healthy GPU worker has
  queue_depth < pool_p50; fallback CPU otherwise.
- HWP_INV_03: A worker whose rolling p50 latency over the last 100
  samples exceeds 2x pool-wide rolling p50 is deprioritized (weight
  0.1x) within 30 seconds.
- HWP_INV_04: Session-stickiness — same session_id routes to same worker
  while the worker is healthy; failover otherwise.
- HWP_INV_05: Burst of N tasks spreads so no single worker's queue
  exceeds 1.5x pool median.
- HWP_INV_06: Once a worker's rolling p50 normalizes back within 1.5x
  pool p50, full weight is restored within 30 seconds.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

R = TypeVar("R")

WorkerKind = Literal["cpu", "gpu"]


class WorkerPoolError(RuntimeError):
    """Base error for pool contract violations."""


class NoEligibleWorkerError(WorkerPoolError):
    """Raised when no registered worker advertises the requested family."""


@dataclass
class Task(Generic[R]):
    """One work item. ``payload`` is caller-defined; pool never inspects it."""

    payload: object
    session_id: str | None = None


@dataclass
class _WorkerState:
    worker_id: str
    capabilities: frozenset[str]
    kind: WorkerKind
    queue_depth: int = 0
    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=100))
    unhealthy_until_ns: int = 0
    # HWP_INV_03 / HWP_INV_06: scalar routing weight. 1.0 = full;
    # 0.1 = deprioritized (worker still gets ~10% of its fair share).
    weight: float = 1.0
    # Running executor for this worker; wraps the caller's fn.
    executor: Callable[[Task[object]], Awaitable[object]] | None = None

    def p50(self) -> float:
        if not self.latencies:
            return 0.0
        return statistics.median(self.latencies)

    def is_healthy(self, now_ns: int) -> bool:
        return now_ns >= self.unhealthy_until_ns


@runtime_checkable
class HeterogeneousWorkerPool(Protocol[R]):
    def register(
        self,
        worker_id: str,
        capabilities: frozenset[str],
        kind: WorkerKind,
        executor: Callable[[Task[object]], Awaitable[R]],
    ) -> None: ...
    def submit(self, task: Task[R], family: str) -> asyncio.Future[R]: ...
    def on_result(self, worker_id: str, latency_ms: float, ok: bool) -> None: ...


class InMemoryHeterogeneousWorkerPool:
    """Reference heterogeneous pool.

    Pure-Python, single-loop. Real deployments swap to a
    ``core/venous/_adapters/ray/`` adapter that backs onto Ray's ActorPool.
    """

    _UNHEALTHY_WINDOW_NS = 30 * 1_000_000_000  # 30 seconds
    # HWP_INV_03: the p50 ratio that triggers deprioritization.
    _DEPRIORITIZE_RATIO = 2.0
    # HWP_INV_06: the p50 ratio below which full weight is restored.
    _RESTORE_RATIO = 1.5
    # HWP_INV_03 / HWP_INV_06: weight applied while deprioritized.
    _DEPRIORITIZED_WEIGHT = 0.1

    def __init__(self) -> None:
        self._workers: dict[str, _WorkerState] = {}
        self._sessions: dict[str, str] = {}  # session_id -> worker_id
        self._runner_tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    def register(
        self,
        worker_id: str,
        capabilities: frozenset[str],
        kind: WorkerKind,
        executor: Callable[[Task[object]], Awaitable[R]],
    ) -> None:
        if kind not in ("cpu", "gpu"):
            raise WorkerPoolError(f"kind MUST be 'cpu' or 'gpu'; got {kind!r}")
        if not capabilities:
            raise WorkerPoolError("capabilities MUST be a non-empty frozenset")
        self._workers[worker_id] = _WorkerState(
            worker_id=worker_id,
            capabilities=frozenset(capabilities),
            kind=kind,
            executor=executor,
        )

    # ------------------------------------------------------------------
    # Observability ingress
    # ------------------------------------------------------------------
    def on_result(self, worker_id: str, latency_ms: float, ok: bool) -> None:
        ws = self._workers.get(worker_id)
        if ws is None:
            return
        ws.queue_depth = max(0, ws.queue_depth - 1)
        if ok:
            ws.latencies.append(latency_ms)
        # HWP_INV_03 / HWP_INV_06: re-evaluate the weight every signal.
        pool_p50 = self._pool_p50()
        if pool_p50 > 0.0 and ws.latencies:
            ratio = ws.p50() / pool_p50
            if ratio >= self._DEPRIORITIZE_RATIO:
                # HWP_INV_03: deprioritize within 30s.
                ws.weight = self._DEPRIORITIZED_WEIGHT
                ws.unhealthy_until_ns = time.monotonic_ns() + self._UNHEALTHY_WINDOW_NS
            elif ratio < self._RESTORE_RATIO and ws.weight < 1.0:
                # HWP_INV_06: p50 has recovered — restore full weight.
                ws.weight = 1.0
                ws.unhealthy_until_ns = 0

    def _pool_p50(self) -> float:
        all_latencies: list[float] = []
        for ws in self._workers.values():
            all_latencies.extend(ws.latencies)
        if not all_latencies:
            return 0.0
        return statistics.median(all_latencies)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def _eligible(self, family: str) -> list[_WorkerState]:
        # HWP_INV_01: only workers advertising the family.
        return [ws for ws in self._workers.values() if family in ws.capabilities]

    def _choose(self, task: Task[R], family: str) -> _WorkerState:
        now_ns = time.monotonic_ns()
        eligible = self._eligible(family)
        if not eligible:
            raise NoEligibleWorkerError(f"no registered worker advertises family {family!r}")

        # HWP_INV_04: session-stickiness if the previous worker is still
        # healthy AND still eligible for this family.
        if task.session_id is not None:
            prev_id = self._sessions.get(task.session_id)
            if prev_id is not None:
                prev = self._workers.get(prev_id)
                if prev is not None and prev.is_healthy(now_ns) and prev in eligible:
                    return prev

        healthy = [w for w in eligible if w.is_healthy(now_ns)]
        if not healthy:
            # All workers are unhealthy — pick the least-bad (lowest p50)
            # to keep forward progress rather than refuse the task.
            return min(eligible, key=lambda w: (w.p50(), w.queue_depth))

        # HWP_INV_02: GPU preference when any healthy GPU has queue < pool_p50-of-queue.
        pool_queue_p50 = statistics.median([w.queue_depth for w in healthy]) if healthy else 0
        gpus = [w for w in healthy if w.kind == "gpu"]
        gpu_available = [w for w in gpus if w.queue_depth < max(pool_queue_p50, 1)]
        if gpu_available:
            # HWP_INV_05: spread via shortest queue among GPUs.
            return min(gpu_available, key=lambda w: (w.queue_depth, w.p50()))

        # Fallback — healthy CPU + any GPU, pick shortest queue.
        return min(healthy, key=lambda w: (w.queue_depth, w.p50()))

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def submit(self, task: Task[R], family: str) -> asyncio.Future[R]:
        ws = self._choose(task, family)
        if task.session_id is not None:
            self._sessions[task.session_id] = ws.worker_id
        ws.queue_depth += 1

        loop = asyncio.get_event_loop()
        fut: asyncio.Future[R] = loop.create_future()
        executor = ws.executor
        assert executor is not None  # noqa: S101 — HWP contract: executor always set at register; assert guards the race-window narrowing

        async def _runner() -> None:
            started = time.monotonic()
            try:
                result = await executor(task)  # type: ignore[arg-type]  # HWP_INV_01: executor is Callable[[Task[object]],...]; task is Task[R] — caller-supplied, never introspected here
            except BaseException as exc:  # noqa: BLE001 — executor outcome must propagate into the future even for BaseException, so callers never hang
                latency_ms = (time.monotonic() - started) * 1000.0
                self.on_result(ws.worker_id, latency_ms, ok=False)
                if not fut.done():
                    fut.set_exception(exc)
                return
            latency_ms = (time.monotonic() - started) * 1000.0
            self.on_result(ws.worker_id, latency_ms, ok=True)
            if not fut.done():
                fut.set_result(result)  # type: ignore[arg-type]  # HWP_INV_04: executor return is Awaitable[object]; Future[R] is caller-typed

        runner = asyncio.ensure_future(_runner())
        self._runner_tasks.add(runner)
        runner.add_done_callback(self._runner_tasks.discard)
        return fut


__all__ = [
    "HeterogeneousWorkerPool",
    "InMemoryHeterogeneousWorkerPool",
    "NoEligibleWorkerError",
    "Task",
    "WorkerKind",
    "WorkerPoolError",
]
