"""Kit-like SOTA emission for the user CRUD calibration spec."""
from __future__ import annotations

import threading
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field

app = FastAPI()


class User(BaseModel):
    id: str
    email: str
    display_name: str


class CreateUserBody(BaseModel):
    email: str = Field(min_length=3)
    display_name: str


class PatchUserBody(BaseModel):
    email: str | None = None
    display_name: str | None = None


_users: dict[str, dict] = {}
_order: list[str] = []          # insertion order (most recent appended)
_email_index: dict[str, str] = {}
_lock = threading.Lock()


def _validate_email(email: str) -> None:
    if not email or "@" not in email or len(email) < 3:
        raise HTTPException(422, "malformed email")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/users", status_code=201)
def create(body: CreateUserBody) -> dict:
    _validate_email(body.email)
    with _lock:
        if body.email in _email_index:
            raise HTTPException(409, "email already registered")
        uid = str(uuid.uuid4())
        rec = {"id": uid, "email": body.email, "display_name": body.display_name,
               "_ts": time.monotonic_ns()}
        _users[uid] = rec
        _email_index[body.email] = uid
        _order.append(uid)
    return {"id": uid, "email": body.email, "display_name": body.display_name}


@app.get("/users/{uid}")
def get_user(uid: str) -> dict:
    with _lock:
        rec = _users.get(uid)
        if not rec:
            raise HTTPException(404, "not found")
        return {"id": rec["id"], "email": rec["email"], "display_name": rec["display_name"]}


@app.get("/users")
def list_users() -> dict:
    with _lock:
        # Most recent first.
        out = []
        for uid in reversed(_order):
            rec = _users[uid]
            out.append({"id": rec["id"], "email": rec["email"], "display_name": rec["display_name"]})
    return {"users": out}


@app.patch("/users/{uid}")
def patch_user(uid: str, body: PatchUserBody) -> dict:
    with _lock:
        rec = _users.get(uid)
        if not rec:
            raise HTTPException(404, "not found")
        if body.email is not None:
            _validate_email(body.email)
            if body.email != rec["email"]:
                if body.email in _email_index:
                    raise HTTPException(409, "email already registered")
                del _email_index[rec["email"]]
                _email_index[body.email] = uid
                rec["email"] = body.email
        if body.display_name is not None:
            rec["display_name"] = body.display_name
        return {"id": rec["id"], "email": rec["email"], "display_name": rec["display_name"]}


@app.delete("/users/{uid}", status_code=204)
def delete_user(uid: str) -> None:
    with _lock:
        rec = _users.pop(uid, None)
        if not rec:
            raise HTTPException(404, "not found")
        _email_index.pop(rec["email"], None)
        if uid in _order:
            _order.remove(uid)
    return None
