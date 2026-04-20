"""Kit-like SOTA rate limiter with class isolation.

Rolling 1-s window per class, enforced with a deque of timestamps and
a lock per class. Bronze gets exactly 1, silver 5, gold 20 in any 1-s
rolling window.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import FastAPI, Header, HTTPException, Response

app = FastAPI()

CLASS_BUDGET = {"gold": 20, "silver": 5, "bronze": 1}
KEY_CLASS = {
    "gold-1": "gold", "gold-2": "gold",
    "silver-1": "silver",
    "bronze-1": "bronze",
}


class ClassLimiter:
    def __init__(self, budget: int) -> None:
        self.budget = budget
        self._hits: deque[float] = deque()
        self._lock = threading.Lock()

    def try_acquire(self) -> tuple[bool, int, int]:
        """Return (admitted, remaining, retry_after_ms)."""
        now = time.monotonic()
        with self._lock:
            # Drop timestamps older than 1s.
            while self._hits and now - self._hits[0] >= 1.0:
                self._hits.popleft()
            if len(self._hits) < self.budget:
                self._hits.append(now)
                return True, self.budget - len(self._hits), 0
            oldest = self._hits[0]
            retry_ms = max(1, int((1.0 - (now - oldest)) * 1000))
            return False, 0, retry_ms


_limiters: dict[str, ClassLimiter] = {
    cls: ClassLimiter(budget) for cls, budget in CLASS_BUDGET.items()
}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/call")
def call(response: Response, x_api_key: str | None = Header(default=None), body: dict | None = None) -> dict:
    if not x_api_key:
        raise HTTPException(400, "X-Api-Key required")
    cls = KEY_CLASS.get(x_api_key)
    if cls is None:
        raise HTTPException(401, "unknown api key")
    ok, remaining, retry = _limiters[cls].try_acquire()
    response.headers["X-RateLimit-Class"] = cls
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    if not ok:
        return _rate_limited_response(cls, retry)
    return {"ok": True, "class": cls}


def _rate_limited_response(cls: str, retry_ms: int) -> dict:
    from fastapi.responses import JSONResponse
    return JSONResponse(
        {"retry_after_ms": retry_ms},
        status_code=429,
        headers={"X-RateLimit-Class": cls, "X-RateLimit-Remaining": "0"},
    )
