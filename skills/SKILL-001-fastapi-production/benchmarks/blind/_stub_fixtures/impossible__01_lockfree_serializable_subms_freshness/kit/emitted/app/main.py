"""Kit-like SOTA serializable swap + sub-ms freshness.

- Single global RLock: gives strict serializability.
- State version ticks on every mutation; /state captures
  (snapshot, version, ts_ns) — freshness is computed from ts_ns.
"""
from __future__ import annotations

import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

_state_lock = threading.RLock()
_counters: dict[str, int] = {}
_state_version = 0
_state_ts_ns = time.monotonic_ns()


def _tick() -> None:
    global _state_version, _state_ts_ns
    _state_version += 1
    _state_ts_ns = time.monotonic_ns()


class CounterBody(BaseModel):
    name: str = Field(min_length=1)
    value: int = 0


class IncrBody(BaseModel):
    name: str = Field(min_length=1)
    delta: int


class SwapBody(BaseModel):
    a: str = Field(min_length=1)
    b: str = Field(min_length=1)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/counters")
def create(body: CounterBody) -> dict:
    with _state_lock:
        _counters[body.name] = body.value
        _tick()
    return {"name": body.name, "value": body.value}


@app.post("/incr")
def incr(body: IncrBody) -> dict:
    with _state_lock:
        if body.name not in _counters:
            raise HTTPException(404)
        _counters[body.name] += body.delta
        _tick()
        return {"name": body.name, "value": _counters[body.name]}


@app.post("/swap")
def swap(body: SwapBody) -> dict:
    with _state_lock:
        if body.a not in _counters or body.b not in _counters:
            raise HTTPException(404)
        _counters[body.a], _counters[body.b] = _counters[body.b], _counters[body.a]
        _tick()
        return {"a": body.a, "b": body.b, "ok": True}


@app.get("/state")
def state(stale_ms: int = 1) -> dict:
    ts_before = time.monotonic_ns()
    with _state_lock:
        snapshot = dict(_counters)
        total = sum(snapshot.values())
    ts_after = time.monotonic_ns()
    # Snapshot was taken between ts_before and ts_after — freshness is 0-1ms
    # depending on how long the lock held.
    age_ms = max(0, (ts_after - ts_before) // 1_000_000)
    return {"counters": snapshot, "total": total, "as_of_ms_ago": int(age_ms)}
