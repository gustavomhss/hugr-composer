"""Naked-like webhook receiver — real-world anti-patterns.

Flaws:
  - Uses `==` for HMAC compare (static scan catches).
  - Increments count for every call (no idempotency) — fails B + A dupe
    + C parallel-count-1.
  - Signature verified over json.dumps(body) instead of raw → tampered
    body passes (fails A tampered and D bit-flip).
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI()
SECRET = b"s3cr3t-bench-key"

_events: dict[str, int] = {}


class Body(BaseModel):
    event_id: str
    event_type: str
    payload: dict


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    sig = request.headers.get("x-signature", "")
    import json
    # BUG: compute signature on re-serialized body, not raw — tampering undetected.
    try:
        data = json.loads(raw)
    except Exception:
        raise HTTPException(400)
    reserialized = json.dumps(data, sort_keys=True).encode()
    signature = hmac.new(SECRET, reserialized, hashlib.sha256).hexdigest()
    # BUG: naive == (static scan flags)
    if signature == sig:
        # BUG: always increment, no idempotency dedup
        eid = data.get("event_id", "")
        _events[eid] = _events.get(eid, 0) + 1
        return {"applied": True, "count": _events[eid]}
    raise HTTPException(401)


@app.get("/events/{event_id}")
def get_event(event_id: str) -> dict:
    if event_id not in _events:
        raise HTTPException(404)
    return {"event_id": event_id, "count": _events[event_id]}


# BUG: GET /events listing omitted — naked agents commonly skip "nice-to-have" routes.

