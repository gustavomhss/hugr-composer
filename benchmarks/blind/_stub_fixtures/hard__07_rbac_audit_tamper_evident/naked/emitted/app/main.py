"""Naked-like RBAC + audit — common shortcomings.

Flaws:
  - Mixes 401/403 (unknown role returns 403, not 401 for unknown user).
  - No hash chain; verify always returns {"ok": true}. Fails D tamper.
  - /audit visible to all users (no admin gate). Fails A reader-audit-403.
  - Tamper endpoint missing. Fails D.
"""
from __future__ import annotations

import threading

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

USERS = {"alice": "admin", "bob": "editor", "carol": "reader"}
ROLE_PERMS = {
    "admin": {"GET", "PUT", "DELETE"},
    "editor": {"GET", "PUT"},
    "reader": {"GET"},
}

_docs: dict[str, dict] = {}
_audit: list[dict] = []
_lock = threading.Lock()


def _require(x_user, need):
    # Bug: missing header → 403 instead of 401
    if not x_user or x_user not in USERS:
        raise HTTPException(403, "not allowed")
    role = USERS[x_user]
    if need not in ROLE_PERMS[role]:
        raise HTTPException(403)
    return x_user


class PutBody(BaseModel):
    body: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/docs/{did}")
def get_doc(did: str, x_user: str = Header(default="")):
    _require(x_user, "GET")
    if did not in _docs:
        raise HTTPException(404)
    return _docs[did]


@app.put("/docs/{did}")
def put_doc(did: str, body: PutBody, x_user: str = Header(default="")):
    _require(x_user, "PUT")
    _docs[did] = {"id": did, "body": body.body}
    _audit.append({"actor": x_user, "action": "update", "target": did})
    return _docs[did]


@app.delete("/docs/{did}", status_code=204)
def delete_doc(did: str, x_user: str = Header(default="")):
    _require(x_user, "DELETE")
    _docs.pop(did, None)
    _audit.append({"actor": x_user, "action": "delete", "target": did})
    return None


@app.get("/audit")
def audit(x_user: str = Header(default="")):
    # Bug: no admin check — any authenticated user can read.
    if not x_user or x_user not in USERS:
        raise HTTPException(403)
    return {"events": list(_audit)}


@app.get("/audit/verify")
def verify(x_user: str = Header(default="")):
    if not x_user or x_user not in USERS:
        raise HTTPException(403)
    # Bug: no hash chain; trivially returns ok.
    return {"ok": True}
