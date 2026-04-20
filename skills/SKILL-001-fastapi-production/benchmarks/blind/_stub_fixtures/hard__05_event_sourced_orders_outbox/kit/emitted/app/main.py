"""Kit-like SOTA event-sourced orders with transactional outbox.

- events[order_id] = list[dict]
- outbox = list[dict]; items marked delivered=True on /outbox/drain
- every state-change function holds a lock and appends BOTH an event
  + an outbox entry under the same critical section.
"""
from __future__ import annotations

import threading
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

_events: dict[str, list[dict]] = {}    # order_id -> events list
_outbox: list[dict] = []               # all events also here, with delivered flag
_lock = threading.Lock()


class CreateOrderBody(BaseModel):
    customer_id: str


class AddItemBody(BaseModel):
    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)


def _append(order_id: str, event_type: str, payload: dict) -> dict:
    """Atomic: append to the aggregate stream AND the outbox."""
    event = {
        "type": event_type,
        "event_type": event_type,  # both keys for robustness
        "order_id": order_id,
        "aggregate_id": order_id,
        "payload": payload,
    }
    _events.setdefault(order_id, []).append(event)
    _outbox.append({**event, "delivered": False})
    return event


def _fold(events: list[dict]) -> dict:
    status = "open"
    items: list[dict] = []
    for ev in events:
        t = ev.get("type")
        if t == "ItemAdded":
            items.append(ev["payload"])
        elif t == "OrderConfirmed":
            status = "confirmed"
        elif t == "OrderCancelled":
            status = "cancelled"
    return {"status": status, "items": items}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/orders", status_code=201)
def create_order(body: CreateOrderBody) -> dict:
    oid = str(uuid.uuid4())
    with _lock:
        _append(oid, "OrderCreated", {"customer_id": body.customer_id})
    return {"order_id": oid, "status": "open"}


@app.post("/orders/{oid}/items")
def add_item(oid: str, body: AddItemBody) -> dict:
    with _lock:
        if oid not in _events:
            raise HTTPException(404)
        state = _fold(_events[oid])
        if state["status"] != "open":
            raise HTTPException(422, "order not open")
        _append(oid, "ItemAdded", {"sku": body.sku, "quantity": body.quantity})
        state = _fold(_events[oid])
    return {"order_id": oid, "status": state["status"], "items": state["items"],
            "version": len(_events[oid])}


@app.post("/orders/{oid}/confirm")
def confirm(oid: str) -> dict:
    with _lock:
        if oid not in _events:
            raise HTTPException(404)
        state = _fold(_events[oid])
        if state["status"] == "confirmed":
            return {"order_id": oid, "status": "confirmed", "version": len(_events[oid])}
        if state["status"] != "open":
            raise HTTPException(422, "cannot confirm")
        _append(oid, "OrderConfirmed", {})
    return {"order_id": oid, "status": "confirmed", "version": len(_events[oid])}


@app.post("/orders/{oid}/cancel")
def cancel(oid: str) -> dict:
    with _lock:
        if oid not in _events:
            raise HTTPException(404)
        state = _fold(_events[oid])
        if state["status"] == "confirmed":
            raise HTTPException(422, "cannot cancel confirmed order")
        if state["status"] == "cancelled":
            return {"order_id": oid, "status": "cancelled", "version": len(_events[oid])}
        _append(oid, "OrderCancelled", {})
    return {"order_id": oid, "status": "cancelled", "version": len(_events[oid])}


@app.get("/orders/{oid}")
def get_order(oid: str) -> dict:
    with _lock:
        if oid not in _events:
            raise HTTPException(404)
        state = _fold(_events[oid])
        return {"order_id": oid, "status": state["status"], "items": state["items"],
                "version": len(_events[oid])}


@app.get("/orders/{oid}/events")
def get_events(oid: str) -> dict:
    with _lock:
        return {"events": list(_events.get(oid, []))}


@app.get("/outbox")
def outbox() -> dict:
    with _lock:
        pending = [e for e in _outbox if not e.get("delivered")]
    return {"pending": pending}


@app.post("/outbox/drain")
def drain() -> dict:
    with _lock:
        n = 0
        for e in _outbox:
            if not e.get("delivered"):
                e["delivered"] = True
                n += 1
    return {"drained": n}
