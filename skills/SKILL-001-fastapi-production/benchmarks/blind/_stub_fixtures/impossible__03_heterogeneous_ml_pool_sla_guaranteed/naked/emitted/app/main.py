"""Naked-like ML pool — routes everything to cpu, no capacity, no stickiness.

Flaws:
  - Always picks cpu → fails tight-deadline (80ms > 30ms).
  - No semaphore → unbounded concurrency (simulated sleep still blocks threads
    but nothing rejects beyond pool capacity).
  - No 503 path → returns 500 on impossible SLA (raises Exception).
  - /pool endpoint returns wrong schema (missing healthy).
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException

app = FastAPI()

CLASSES = {"cpu": 80, "gpu": 15}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


import random as _r


@app.post("/infer")
def infer(body: dict):
    sid = body["session_id"]        # KeyError → 500 on missing
    deadline = int(body["deadline_ms"])
    prompt = body["prompt"]
    # BUG: 1 in 2 requests simulates a crash (naive unhandled exception).
    if _r.random() < 0.5:
        raise RuntimeError("simulated worker crash")
    # BUG: always picks cpu — ignores deadline.
    chosen = "cpu"
    time.sleep(CLASSES[chosen] / 1000.0)
    return {
        "worker": chosen, "result": f"echo:{prompt}",
        "latency_ms": CLASSES[chosen], "session_id": sid,
    }


@app.get("/pool")
def pool() -> dict:
    # BUG: wrong shape — missing `healthy`, `in_flight` mislabeled.
    return {"cpu": {"count": 0}, "gpu": {"count": 0}}
