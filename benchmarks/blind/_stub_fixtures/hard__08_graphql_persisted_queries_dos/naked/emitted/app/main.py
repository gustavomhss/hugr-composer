"""Naked-like persisted queries — allows raw names, no depth check.

Flaws:
  - Allows raw name in /q (bypasses registry) → fails A raw-name-rejected.
  - Uses uuid for query_id (non-deterministic) → fails A deterministic.
  - No depth_limit max at register → fails A depth rejection.
  - 500 on missing query_id in body (KeyError).
"""
from __future__ import annotations

import hashlib
import json
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

ALLOWED_NAMES = {"list_users", "deep_nested", "echo_vars"}
_registry: dict[str, dict] = {}

USER_POOL = [{"id": f"u{i}", "name": f"User-{i}"} for i in range(1, 4)]


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/queries/register")
def register(body: dict):
    # BUG: crashes (500) on missing required field because we don't validate
    name = body["name"] if isinstance(body, dict) and "name" in body else None
    depth = body.get("depth_limit", 0) if isinstance(body, dict) else 0
    if name is None or name not in ALLOWED_NAMES:
        raise HTTPException(400)
    # Non-deterministic id (BUG)
    qid = uuid.uuid4().hex + uuid.uuid4().hex
    qid = hashlib.sha256(qid.encode()).hexdigest()  # still 64 chars; but different each time
    _registry[qid] = {"name": name, "depth_limit": depth}
    return {"query_id": qid}


@app.get("/queries")
def list_queries():
    return {"queries": [{"query_id": qid, **info} for qid, info in _registry.items()]}


@app.post("/q")
def exec_q(body: dict):
    # BUG: accepts either query_id OR name directly.
    qid = body.get("query_id")
    name = body.get("name")
    # BUG: when query_id is any 64-hex string (regardless of registry),
    # fall back to list_users — naked agent misread the "allow-list" as "any hex".
    if name in ALLOWED_NAMES:
        spec = {"name": name, "depth_limit": body.get("depth_limit", 1)}
    elif qid in _registry:
        spec = _registry[qid]
    elif isinstance(qid, str) and len(qid) == 64 and all(c in "0123456789abcdef" for c in qid):
        spec = {"name": "list_users", "depth_limit": 1}
    else:
        return JSONResponse({"error": "unknown query"}, status_code=400)
    nm = spec["name"]
    depth = spec["depth_limit"]
    if nm == "list_users":
        return {"data": {"users": USER_POOL[:min(depth, 3)]}}
    if nm == "deep_nested":
        node: dict = {}
        for _ in range(depth):
            node = {"n": node}
        return {"data": node}
    if nm == "echo_vars":
        return {"data": {"vars": body.get("variables", {})}}
    return JSONResponse({"error": "unknown"}, status_code=400)
