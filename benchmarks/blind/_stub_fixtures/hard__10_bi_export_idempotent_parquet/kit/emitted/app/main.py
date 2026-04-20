"""Kit-like SOTA export facade."""
from __future__ import annotations

import datetime as dt
import re
import threading
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

DATASETS = {"orders": 100, "users": 50, "events": 1000}
PART_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_exports: dict[tuple[str, str], dict] = {}
_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_lock = threading.Lock()


class ExportBody(BaseModel):
    dataset: str
    partition: str
    force: bool = False


def _validate(dataset: str, partition: str) -> None:
    if dataset not in DATASETS:
        raise HTTPException(400, "unknown dataset")
    if not PART_RE.match(partition):
        raise HTTPException(400, "malformed partition")
    # also ensure it's a valid date
    try:
        dt.date.fromisoformat(partition)
    except ValueError:
        raise HTTPException(400, "not a valid date")


def _lock_for(pair: tuple[str, str]) -> threading.Lock:
    with _locks_lock:
        if pair not in _locks:
            _locks[pair] = threading.Lock()
        return _locks[pair]


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/exports")
def create_export(body: ExportBody) -> dict:
    _validate(body.dataset, body.partition)
    pair = (body.dataset, body.partition)
    lock = _lock_for(pair)
    with lock:
        if pair in _exports and not body.force:
            rec = _exports[pair]
            return {"status": "already_exists", **rec}
        eid = str(uuid.uuid4())
        rows = DATASETS[body.dataset]
        rec = {"dataset": body.dataset, "partition": body.partition,
               "export_id": eid, "rows": rows, "bytes": rows * 64}
        replaced = pair in _exports
        _exports[pair] = rec
    return {"status": "replaced" if replaced else "created", **rec}


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
