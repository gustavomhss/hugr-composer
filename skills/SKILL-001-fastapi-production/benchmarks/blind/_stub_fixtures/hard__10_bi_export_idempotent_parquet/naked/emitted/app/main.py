"""Naked-like export facade — ignores force + validation.

Flaws:
  - No lock → concurrent creates overwrite each other.
  - Accepts any dataset → fails A invalid dataset.
  - Ignores force flag → fails A force-replaces.
  - Accepts any partition string → fails A malformed.
  - bytes formula off-by-N → fails B property.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException

app = FastAPI()

DATASETS = {"orders": 100, "users": 50, "events": 1000}

_exports: dict[tuple[str, str], dict] = {}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/exports")
def create_export(body: dict):
    if not isinstance(body, dict):
        raise HTTPException(400)
    ds = body.get("dataset")
    part = body.get("partition")
    if not isinstance(ds, str) or not isinstance(part, str):
        raise HTTPException(400)
    # BUG: no validation on dataset or partition format
    pair = (ds, part)
    if pair in _exports:
        # BUG: ignores force
        rec = _exports[pair]
        return {"status": "already_exists", **rec}
    eid = str(uuid.uuid4())
    rows = DATASETS.get(ds, 42)   # bug: fallback to 42 for unknown datasets
    # BUG: uses 60 instead of 64
    rec = {"dataset": ds, "partition": part,
           "export_id": eid, "rows": rows, "bytes": rows * 60}
    _exports[pair] = rec
    return {"status": "created", **rec}


@app.get("/exports")
def list_exports() -> dict:
    return {"exports": list(_exports.values())}


@app.get("/exports/{dataset}/{partition}")
def get_export(dataset: str, partition: str) -> dict:
    rec = _exports.get((dataset, partition))
    if not rec:
        raise HTTPException(404)
    return rec


@app.delete("/exports/{dataset}/{partition}", status_code=204)
def delete_export(dataset: str, partition: str) -> None:
    if (dataset, partition) not in _exports:
        raise HTTPException(404)
    del _exports[(dataset, partition)]
    return None
