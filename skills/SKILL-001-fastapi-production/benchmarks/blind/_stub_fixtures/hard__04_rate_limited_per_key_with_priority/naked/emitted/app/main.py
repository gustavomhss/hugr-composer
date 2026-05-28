"""Naked-like rate limiter — one shared bucket, fixed window, 401s bill.

Flaws:
  - Single shared counter for all classes (fails class isolation under flood).
  - Fixed 1-second integer window, resets at "top of second" (edge cases).
  - 401s are counted toward the shared budget (D chaos).
  - Missing headers X-RateLimit-* on response (A).
  - Race: counter++ without lock (C parallel-bronze).
"""
from __future__ import annotations

import time

from fastapi import FastAPI, Header, HTTPException

app = FastAPI()

# All keys share this bucket; budget = max(gold). Fails isolation.
CLASS_BUDGET = {"gold": 10, "silver": 3, "bronze": 1}  # Bug: gold=10 (≠20), silver=3 (≠5)
KEY_CLASS = {
    # Bug: "gold-2" missing — naked agent only partially transcribed the registry.
    "gold-1": "gold",
    "silver-1": "silver",
    "bronze-1": "bronze",
}

_window_start: float = time.monotonic()
_count: int = 0


def _reset_if_window_rolled() -> None:
    global _window_start, _count
    now = time.monotonic()
    if now - _window_start >= 1.0:
        _window_start = now
        _count = 0


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/call")
def call(x_api_key: str = Header(...), body: dict | None = None):
    global _count
    _reset_if_window_rolled()
    cls = KEY_CLASS.get(x_api_key)
    if cls is None:
        # Bug: still bump the counter on unknown keys (401 consumes budget).
        _count += 1
        raise HTTPException(401)
    # Bug: off-by-one — 2 bronze calls both pass (uses >, not >=).
    current = _count
    if current > CLASS_BUDGET[cls]:
        from fastapi.responses import JSONResponse
        return JSONResponse({"retry_after_ms": 500}, status_code=429)
    _count = current + 1
    return {"ok": True, "class": cls}
