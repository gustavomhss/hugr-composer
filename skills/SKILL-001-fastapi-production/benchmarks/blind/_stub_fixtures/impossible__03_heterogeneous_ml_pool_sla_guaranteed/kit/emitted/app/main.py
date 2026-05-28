"""Kit-like SOTA heterogeneous ML pool with SLA routing + stickiness."""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

CLASSES = {
    "cpu": {"latency_ms": 80, "capacity": 3},
    "gpu": {"latency_ms": 15, "capacity": 1},
}


class WorkerPool:
    def __init__(self, name: str, latency_ms: int, capacity: int) -> None:
        self.name = name
        self.latency_ms = latency_ms
        self.capacity = capacity
        self._sem = threading.Semaphore(capacity)
        self._in_flight = 0
        self._latencies: deque[float] = deque(maxlen=10)
        self._lock = threading.Lock()

    def try_acquire(self, timeout_ms: int) -> bool:
        return self._sem.acquire(timeout=timeout_ms / 1000.0)

    def release(self) -> None:
        self._sem.release()

    def record(self, latency_ms: float) -> None:
        with self._lock:
            self._latencies.append(latency_ms)

    def in_flight(self) -> int:
        return self.capacity - self._sem._value  # type: ignore[attr-defined]

    def latency_p50(self) -> float:
        with self._lock:
            if not self._latencies:
                return float(self.latency_ms)
            s = sorted(self._latencies)
            return s[len(s) // 2]

    def healthy(self) -> bool:
        return self.latency_p50() <= self.latency_ms * 1.5


_pools = {cls: WorkerPool(cls, cfg["latency_ms"], cfg["capacity"])
          for cls, cfg in CLASSES.items()}
_session_hint: dict[str, tuple[str, float]] = {}  # session -> (class, ts)
_session_lock = threading.Lock()


def _pick_class(deadline_ms: int, session_id: str) -> str | None:
    now = time.monotonic()
    # Stickiness: if session was seen in last 500ms and pool is healthy + meets SLA, prefer it.
    with _session_lock:
        hint = _session_hint.get(session_id)
        if hint and now - hint[1] < 0.5:
            cls = hint[0]
            if (_pools[cls].healthy()
                    and CLASSES[cls]["latency_ms"] + 5 <= deadline_ms):
                return cls
    # Otherwise pick fastest class that can meet the SLA with some headroom.
    for cls in ("gpu", "cpu"):
        if (_pools[cls].healthy()
                and CLASSES[cls]["latency_ms"] + 5 <= deadline_ms):
            return cls
    return None


class InferBody(BaseModel):
    session_id: str = Field(min_length=1)
    deadline_ms: int = Field(ge=1)
    prompt: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/infer")
def infer(body: InferBody):
    t0 = time.monotonic()
    cls = _pick_class(body.deadline_ms, body.session_id)
    if cls is None:
        return JSONResponse({"error": "sla_infeasible"}, status_code=503)
    pool = _pools[cls]
    # Try to acquire a slot within the remaining budget.
    elapsed_ms = (time.monotonic() - t0) * 1000
    remaining_ms = body.deadline_ms - elapsed_ms - CLASSES[cls]["latency_ms"]
    if remaining_ms < 0:
        return JSONResponse({"error": "sla_infeasible"}, status_code=503)
    if not pool.try_acquire(int(remaining_ms)):
        return JSONResponse({"error": "sla_infeasible"}, status_code=503)
    try:
        # Simulate work.
        time.sleep(CLASSES[cls]["latency_ms"] / 1000.0)
        latency_ms = int((time.monotonic() - t0) * 1000)
        pool.record(latency_ms)
        with _session_lock:
            _session_hint[body.session_id] = (cls, time.monotonic())
        return {"worker": cls, "result": f"echo:{body.prompt}",
                "latency_ms": latency_ms, "session_id": body.session_id}
    finally:
        pool.release()


@app.get("/pool")
def pool() -> dict:
    return {
        cls: {
            "in_flight": _pools[cls].in_flight(),
            "latency_p50_ms": _pools[cls].latency_p50(),
            "healthy": _pools[cls].healthy(),
        }
        for cls in CLASSES
    }
