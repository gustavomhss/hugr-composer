"""Naked-like ingest — delivers in arrival order (no reorder).

Flaws:
  - No buffer: /events appends to delivered immediately → fails A reverse,
    B property, C interleaved, D partition.
  - /gaps always returns [] → fails A gap.
  - /broker/_partition endpoint not implemented → 404.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

app = FastAPI()

_delivered: dict[str, list[dict]] = {}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/events", status_code=202)
def ingest(body: dict):
    # Crash on missing fields (no validation → 500 on malformed).
    agg = body["aggregate_id"]
    seq = body["sequence"]
    if not isinstance(seq, int):
        raise HTTPException(422)
    _delivered.setdefault(agg, []).append(
        {"sequence": seq, "payload": body.get("payload", {})}
    )
    return {"buffered": False, "delivered_count": len(_delivered[agg])}


@app.get("/delivered/{agg}")
def delivered(agg: str) -> dict:
    return {"events": _delivered.get(agg, [])}


@app.get("/gaps/{agg}")
def gaps(agg: str) -> dict:
    return {"gaps": []}


# /broker/_partition intentionally absent.
