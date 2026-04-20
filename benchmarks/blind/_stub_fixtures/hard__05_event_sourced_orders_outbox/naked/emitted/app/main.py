"""Naked-like orders — stores state directly, outbox is dual-write.

Flaws:
  - Stores status mutably, events list is reconstructed from mutation log
    (acceptable-looking but confirm emits TWICE on replay → fails A idempotent)
  - No lock on /orders creation → still OK for GIL usually
  - Outbox written in a separate step, with a random 10% "dropped write"
    → breaks B property + C 100-parallel outbox count
  - Missing /outbox/drain endpoint → breaks A drain test
  - Cancel on confirmed order returns 200 (not 422) → breaks A
"""
from __future__ import annotations

import random
import threading
import uuid

from fastapi import FastAPI, HTTPException

app = FastAPI()

_orders: dict[str, dict] = {}    # order_id -> {status, items, events}
_events: dict[str, list[dict]] = {}
_outbox: list[dict] = []
_lock = threading.Lock()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


def _outbox_append(event: dict) -> None:
    # Dual-write: sometimes the outbox write fails silently (simulating
    # the dreaded dropped write).
    if random.random() < 0.10:
        return
    _outbox.append({**event, "delivered": False})


@app.post("/orders", status_code=201)
def create_order(body: dict) -> dict:
    oid = str(uuid.uuid4())
    _orders[oid] = {"status": "open", "items": []}
    ev = {"type": "OrderCreated", "event_type": "OrderCreated",
          "order_id": oid, "aggregate_id": oid, "payload": body}
    _events.setdefault(oid, []).append(ev)
    _outbox_append(ev)
    return {"order_id": oid, "status": "open"}


@app.post("/orders/{oid}/items")
def add_item(oid: str, body: dict) -> dict:
    if oid not in _orders:
        raise HTTPException(404)
    if not isinstance(body.get("sku"), str) or not body.get("sku"):
        raise HTTPException(422)
    q = body.get("quantity")
    if not isinstance(q, int) or q <= 0:
        raise HTTPException(422)
    _orders[oid]["items"].append(body)
    ev = {"type": "ItemAdded", "event_type": "ItemAdded",
          "order_id": oid, "aggregate_id": oid, "payload": body}
    _events.setdefault(oid, []).append(ev)
    _outbox_append(ev)
    return {"order_id": oid, **_orders[oid]}


@app.post("/orders/{oid}/confirm")
def confirm(oid: str) -> dict:
    if oid not in _orders:
        raise HTTPException(404)
    # BUG: no idempotency check — emits a new OrderConfirmed each call.
    _orders[oid]["status"] = "confirmed"
    ev = {"type": "OrderConfirmed", "event_type": "OrderConfirmed",
          "order_id": oid, "aggregate_id": oid, "payload": {}}
    _events.setdefault(oid, []).append(ev)
    _outbox_append(ev)
    return {"order_id": oid, "status": "confirmed",
            "version": len(_events.get(oid, []))}


@app.post("/orders/{oid}/cancel")
def cancel(oid: str) -> dict:
    if oid not in _orders:
        raise HTTPException(404)
    # BUG: naked doesn't check status — allows cancel of confirmed.
    _orders[oid]["status"] = "cancelled"
    ev = {"type": "OrderCancelled", "event_type": "OrderCancelled",
          "order_id": oid, "aggregate_id": oid, "payload": {}}
    _events.setdefault(oid, []).append(ev)
    _outbox_append(ev)
    return {"order_id": oid, "status": "cancelled"}


@app.get("/orders/{oid}")
def get_order(oid: str) -> dict:
    if oid not in _orders:
        raise HTTPException(404)
    return {"order_id": oid, **_orders[oid],
            "version": len(_events.get(oid, []))}


@app.get("/orders/{oid}/events")
def get_events(oid: str) -> dict:
    return {"events": list(_events.get(oid, []))}


@app.get("/outbox")
def outbox() -> dict:
    return {"pending": [e for e in _outbox if not e.get("delivered")]}


# BUG: no /outbox/drain endpoint at all — naked agent forgot it.
