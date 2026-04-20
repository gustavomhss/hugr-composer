"""Naked-like auth refresh — several real anti-patterns.

Deliberate flaws:
  - No family tracking: used refresh tokens keep working forever.
    → Fails B property (replay detection) and A logout-revokes-family.
  - Race on /refresh: check-then-mutate without lock, multiple rotations
    possible under concurrency. → Fails C.
  - Access token IS the session_id (predictable, non-opaque).
    Actually, worse: the "access_token" is "access_" + username + uuid,
    so contains the username. → Fails A access_token_is_not_username.
  - /logout removes only the refresh token, not access tokens.
  - 500 on missing Authorization (no header check). → Fails D.

Expected: ~30%, within band [13, 48] for predicted 28.
"""
from __future__ import annotations

import secrets
import time
import uuid

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI()

# Pure-dict state with no locking.
_access_to_user: dict[str, str] = {}
_refresh_to_access: dict[str, str] = {}


class LoginBody(BaseModel):
    username: str


class RefreshBody(BaseModel):
    refresh_token: str


class LogoutBody(BaseModel):
    refresh_token: str


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/login")
def login(body: LoginBody) -> dict:
    sid = str(uuid.uuid4())
    # Bug: includes username in access token → static-scan-safe but Layer A flags
    access = f"access_{body.username}_{secrets.token_urlsafe(16)}"
    refresh = secrets.token_urlsafe(24)
    _access_to_user[access] = body.username
    _refresh_to_access[refresh] = access
    return {"access_token": access, "refresh_token": refresh, "session_id": sid}


@app.post("/refresh")
def refresh(body: RefreshBody) -> dict:
    # No lock, no rotation tracking. Check-then-act window is wide.
    old_access = _refresh_to_access.get(body.refresh_token)
    if not old_access:
        raise HTTPException(401)
    user = _access_to_user.get(old_access, "unknown")
    # Simulate a slow path to widen the race window:
    time.sleep(0.002)
    new_access = f"access_{user}_{secrets.token_urlsafe(16)}"
    new_refresh = secrets.token_urlsafe(24)
    _access_to_user[new_access] = user
    _refresh_to_access[new_refresh] = new_access
    # BUG: does NOT delete the old refresh token → replay always works.
    return {"access_token": new_access, "refresh_token": new_refresh, "session_id": "na"}


@app.get("/whoami")
def whoami(authorization: str = Header(...)):
    # Bug: `Header(...)` means missing header raises 422 (4xx, acceptable)
    # but we then assume "Bearer " prefix blindly.
    tok = authorization.split(" ", 1)[1] if " " in authorization else authorization
    user = _access_to_user.get(tok)
    if not user:
        raise HTTPException(401)
    return {"username": user, "session_id": "na"}


@app.post("/logout", status_code=204)
def logout(body: LogoutBody):
    # Bug: does not revoke access tokens, only the refresh entry.
    _refresh_to_access.pop(body.refresh_token, None)
    return None
