"""Heterogeneous ML inference pool — queue + latency-aware routing."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class Worker:
    id: str
    kind: str                         # "cpu" | "gpu"
    capabilities: set[str]            # {"llama", "bert", ...}
    queue_depth: int = 0
    p50_latency_ms: float = 100.0
    healthy: bool = True


class HeterogeneousWorkerPool:
    """Routes tasks by capability + (queue_depth × latency_penalty)."""

    def __init__(self) -> None:
        self._workers: list[Worker] = []
        self._stickiness: dict[str, str] = {}  # session_id -> worker_id
        self._lock = threading.Lock()

    def add(self, worker: Worker) -> None:
        with self._lock:
            self._workers.append(worker)

    def _candidates(self, model_family: str) -> list[Worker]:
        return [w for w in self._workers
                if w.healthy and model_family in w.capabilities]

    def _score(self, worker: Worker) -> float:
        # Lower is better. Latency penalty scales linearly.
        return (worker.queue_depth + 1) * (worker.p50_latency_ms / 100.0)

    def route(self, *, model_family: str, session_id: str | None = None,
              prefer_gpu: bool = True) -> Worker:
        with self._lock:
            if session_id is not None:
                stuck = self._stickiness.get(session_id)
                if stuck is not None:
                    for w in self._workers:
                        if w.id == stuck and w.healthy and model_family in w.capabilities:
                            w.queue_depth += 1
                            return w
                    # Stuck worker is unhealthy — invalidate and re-route.
                    del self._stickiness[session_id]

            cands = self._candidates(model_family)
            if not cands:
                raise RuntimeError(f"no worker for {model_family}")
            if prefer_gpu and any(w.kind == "gpu" for w in cands):
                cands = [w for w in cands if w.kind == "gpu"] or cands
            chosen = min(cands, key=self._score)
            chosen.queue_depth += 1
            if session_id is not None:
                self._stickiness[session_id] = chosen.id
            return chosen

    def complete(self, worker_id: str) -> None:
        with self._lock:
            for w in self._workers:
                if w.id == worker_id:
                    w.queue_depth = max(0, w.queue_depth - 1)

    def set_latency(self, worker_id: str, p50_ms: float) -> None:
        with self._lock:
            for w in self._workers:
                if w.id == worker_id:
                    w.p50_latency_ms = p50_ms

    def mark_unhealthy(self, worker_id: str) -> None:
        with self._lock:
            for w in self._workers:
                if w.id == worker_id:
                    w.healthy = False

    def snapshot(self) -> list[Worker]:
        with self._lock:
            return [Worker(**w.__dict__) for w in self._workers]
