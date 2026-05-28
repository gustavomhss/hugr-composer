"""Kit-like persisted-query registry."""
from __future__ import annotations

import hashlib
import json
import threading

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI()

ALLOWED_NAMES = {"list_users", "deep_nested", "echo_vars"}
MAX_DEPTH = 6

_registry: dict[str, dict] = {}
_lock = threading.Lock()

USER_POOL = [{"id": f"u{i}", "name": f"User-{i}"} for i in range(1, 4)]


class RegisterBody(BaseModel):
    name: str = Field(min_length=1)
    depth_limit: int = Field(ge=0)


def _compute_id(name: str, depth: int) -> str:
    return hashlib.sha256(
        json.dumps({"name": name, "depth_limit": depth}, sort_keys=True).encode()
    ).hexdigest()


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/queries/register")
def register(body: RegisterBody):
    if body.name not in ALLOWED_NAMES:
        raise HTTPException(400, "unknown query name")
    if body.depth_limit > MAX_DEPTH:
        raise HTTPException(400, f"depth_limit > {MAX_DEPTH}")
    qid = _compute_id(body.name, body.depth_limit)
    with _lock:
        _registry[qid] = {"name": body.name, "depth_limit": body.depth_limit}
    return {"query_id": qid}


@app.get("/queries")
def list_queries():
    with _lock:
        return {"queries": [{"query_id": qid, **info} for qid, info in _registry.items()]}


@app.post("/q")
async def exec_q(body: dict):
    if not isinstance(body, dict) or "query_id" not in body:
        return JSONResponse({"error": "missing query_id"}, status_code=400)
    qid = body.get("query_id")
    if not isinstance(qid, str):
        return JSONResponse({"error": "invalid query_id"}, status_code=400)
    with _lock:
        spec = _registry.get(qid)
    if not spec:
        return JSONResponse({"error": "unknown query"}, status_code=400)
    name = spec["name"]
    depth = spec["depth_limit"]
    vars_ = body.get("variables", {}) or {}
    if name == "list_users":
        n = min(max(0, int(depth)), len(USER_POOL))
        return {"data": {"users": USER_POOL[:n]}}
    if name == "deep_nested":
        node: dict = {}
        for _ in range(depth):
            node = {"n": node}
        return {"data": node}
    if name == "echo_vars":
        return {"data": {"vars": vars_}}
    return JSONResponse({"error": "unknown query"}, status_code=400)
