"""Naked-like emission — typical shortcuts from a rushed junior.

Deliberate flaws:
  - No duplicate-email check → returns 201 instead of 409 on dup. (-1 A test)
  - No malformed email validation → accepts "not-an-email". (-1 A test)
  - Listing order is insertion order (oldest first) instead of recent-first.
    (-1 A test)
  - PATCH overwrites all fields including email even when not provided
    (doesn't happen here but an accidental None assignment might).

Expected: passes 5/8 A + 1/1 B = 6/9 ~ 67%. Predicted 80, band [65, 100] — OK.
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException

app = FastAPI()

_users: dict[str, dict] = {}


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/users", status_code=201)
def create(body: dict) -> dict:
    # No email validation, no duplicate check
    uid = str(uuid.uuid4())
    rec = {
        "id": uid,
        "email": body.get("email", ""),
        "display_name": body.get("display_name", ""),
    }
    _users[uid] = rec
    return rec


@app.get("/users/{uid}")
def get_user(uid: str) -> dict:
    rec = _users.get(uid)
    if not rec:
        raise HTTPException(404)
    return rec


@app.get("/users")
def list_users() -> dict:
    # Insertion order (oldest first) — fails "recent first" test
    return {"users": list(_users.values())}


@app.patch("/users/{uid}")
def patch_user(uid: str, body: dict) -> dict:
    rec = _users.get(uid)
    if not rec:
        raise HTTPException(404)
    if "email" in body:
        rec["email"] = body["email"]
    if "display_name" in body:
        rec["display_name"] = body["display_name"]
    return rec


@app.delete("/users/{uid}", status_code=204)
def delete_user(uid: str) -> None:
    if uid not in _users:
        raise HTTPException(404)
    del _users[uid]
    return None
