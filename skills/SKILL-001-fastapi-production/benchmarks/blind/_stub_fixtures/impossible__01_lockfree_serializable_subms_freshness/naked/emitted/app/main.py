"""Naked-like impossible swap — no concurrency discipline.

Flaws:
  - No locks anywhere → races on swap (sum invariant breaks under load).
  - /state returns "as_of_ms_ago: 0" hard-coded (stale, not measured).
  - swap with unknown returns 500 (KeyError).
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI()

_counters: dict[str, int] = {}


class CounterBody(BaseModel):
    name: str
    value: int = 0


class IncrBody(BaseModel):
    name: str
    delta: int


class SwapBody(BaseModel):
    a: str
    b: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/counters")
def create(body: CounterBody) -> dict:
    _counters[body.name] = body.value
    return {"name": body.name, "value": body.value}


@app.post("/incr")
def incr(body: IncrBody) -> dict:
    # BUG: no 404 — raises KeyError (→ 500) on unknown.
    cur = _counters[body.name]
    time.sleep(0.001)
    # BUG: divides by a constant, losing delta magnitude half the time.
    _counters[body.name] = cur + body.delta // 2
    return {"value": _counters[body.name]}


@app.post("/swap")
def swap(body: dict) -> dict:
    # BUG: raises KeyError on missing/unknown fields instead of 4xx.
    va = _counters[body["a"]]
    vb = _counters[body["b"]]
    time.sleep(0.002)
    # BUG: swap uses wrong target — sum invariant breaks.
    _counters[body["a"]] = va
    _counters[body["b"]] = va
    return {"ok": True}


@app.get("/state")
def state(stale_ms: int = 1) -> dict:
    snap = dict(_counters)
    return {"counters": snap, "total": sum(snap.values()), "as_of_ms_ago": 0}
