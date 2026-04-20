"""Kit-like SOTA signed webhook receiver."""
from __future__ import annotations

import hashlib
import hmac
import json
import threading

from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

SECRET = b"s3cr3t-bench-key"

# IdempotencyStore: event_id → count (always 1 after first accept)
_events: dict[str, int] = {}
_lock = threading.Lock()


def _verify(raw: bytes, signature: str) -> bool:
    expected = hmac.new(SECRET, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    raw = await request.body()
    sig = request.headers.get("x-signature", "") or request.headers.get("X-Signature", "")
    if not _verify(raw, sig):
        raise HTTPException(401, "invalid signature")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid json")
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise HTTPException(422, "missing event_id")
    with _lock:
        if event_id in _events:
            return {"applied": False, "count": _events[event_id]}
        _events[event_id] = 1
    return {"applied": True, "count": 1}


@app.get("/events/{event_id}")
def get_event(event_id: str) -> dict:
    with _lock:
        if event_id not in _events:
            raise HTTPException(404)
        return {"event_id": event_id, "count": _events[event_id]}


@app.get("/events")
def list_events() -> dict:
    with _lock:
        return {"events": [{"event_id": k, "count": v} for k, v in _events.items()]}
