"""Kit-like SOTA RBAC + tamper-evident audit."""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

USERS = {"alice": "admin", "bob": "editor", "carol": "reader"}
ROLE_PERMS = {
    "admin": {"GET", "PUT", "DELETE", "AUDIT"},
    "editor": {"GET", "PUT"},
    "reader": {"GET"},
}

_docs: dict[str, dict] = {}
_audit: list[dict] = []
_lock = threading.Lock()
GENESIS = "0" * 64


def _compute_hash(prev: str, payload: dict) -> str:
    b = prev.encode() + b"|" + json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(b).hexdigest()


def _append_audit(actor: str, action: str, target: str) -> None:
    with _lock:
        idx = len(_audit)
        prev_hash = _audit[-1]["this_hash"] if _audit else GENESIS
        payload = {"index": idx, "actor": actor, "action": action, "target": target}
        this_hash = _compute_hash(prev_hash, payload)
        _audit.append({**payload, "prev_hash": prev_hash, "this_hash": this_hash})


def _require(x_user: str | None, need: str) -> str:
    if not x_user:
        raise HTTPException(401, "missing X-User")
    role = USERS.get(x_user)
    if role is None:
        raise HTTPException(401, "unknown user")
    if need not in ROLE_PERMS[role]:
        raise HTTPException(403, f"{role} cannot {need}")
    return x_user


class PutBody(BaseModel):
    body: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/docs/{did}")
def get_doc(did: str, x_user: str | None = Header(default=None)) -> dict:
    _require(x_user, "GET")
    d = _docs.get(did)
    if not d:
        raise HTTPException(404)
    return d


@app.put("/docs/{did}")
def put_doc(did: str, body: PutBody, x_user: str | None = Header(default=None)) -> dict:
    actor = _require(x_user, "PUT")
    with _lock:
        _docs[did] = {"id": did, "body": body.body}
    _append_audit(actor, "update", did)
    return _docs[did]


@app.delete("/docs/{did}", status_code=204)
def delete_doc(did: str, x_user: str | None = Header(default=None)) -> None:
    actor = _require(x_user, "DELETE")
    with _lock:
        _docs.pop(did, None)
    _append_audit(actor, "delete", did)
    return None


@app.get("/audit")
def get_audit(x_user: str | None = Header(default=None)) -> dict:
    _require(x_user, "AUDIT")
    with _lock:
        return {"events": list(_audit)}


@app.get("/audit/verify")
def verify(x_user: str | None = Header(default=None)) -> dict:
    _require(x_user, "AUDIT")
    with _lock:
        prev = GENESIS
        for i, r in enumerate(_audit):
            payload = {"index": r["index"], "actor": r["actor"],
                       "action": r["action"], "target": r["target"]}
            expected = _compute_hash(prev, payload)
            if r.get("prev_hash") != prev or r.get("this_hash") != expected or r["index"] != i:
                return {"ok": False, "broken_index": i}
            prev = r["this_hash"]
    return {"ok": True}


class TamperBody(BaseModel):
    at_index: int


@app.post("/audit/_test_tamper")
def tamper(body: TamperBody, x_user: str | None = Header(default=None)) -> dict:
    _require(x_user, "AUDIT")
    with _lock:
        if body.at_index >= len(_audit):
            raise HTTPException(400)
        _audit[body.at_index]["target"] = _audit[body.at_index]["target"] + "!MUTATED"
    return {"tampered": True}
