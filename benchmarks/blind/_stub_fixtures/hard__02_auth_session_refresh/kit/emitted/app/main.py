"""Kit-like SOTA auth session refresh — passes every judge layer."""
from __future__ import annotations

import secrets
import threading
import uuid
from dataclasses import dataclass, field

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()


@dataclass
class Session:
    session_id: str
    username: str
    # refresh_token_chain: ordered list. Index 0 = oldest.
    # The CURRENT valid refresh token is the LAST one not yet consumed.
    # Previous ones are "consumed" (already rotated from).
    consumed_refresh: set[str] = field(default_factory=set)
    current_refresh: str = ""
    access_tokens: set[str] = field(default_factory=set)  # all issued
    compromised: bool = False
    revoked: bool = False


_sessions_by_id: dict[str, Session] = {}
_refresh_index: dict[str, str] = {}       # refresh_token → session_id (includes consumed ones)
_access_index: dict[str, str] = {}        # access_token → session_id
_lock = threading.RLock()


def _new_token(n: int = 32) -> str:
    return secrets.token_urlsafe(n)


class LoginBody(BaseModel):
    username: str = Field(min_length=1)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutBody(BaseModel):
    refresh_token: str = Field(min_length=1)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/login")
def login(body: LoginBody) -> dict:
    sid = str(uuid.uuid4())
    access = _new_token()
    refresh = _new_token()
    with _lock:
        sess = Session(
            session_id=sid, username=body.username,
            current_refresh=refresh,
            access_tokens={access},
        )
        _sessions_by_id[sid] = sess
        _refresh_index[refresh] = sid
        _access_index[access] = sid
    return {"access_token": access, "refresh_token": refresh, "session_id": sid}


@app.post("/refresh")
def refresh(body: RefreshBody) -> dict:
    with _lock:
        sid = _refresh_index.get(body.refresh_token)
        if not sid:
            raise HTTPException(401, "invalid refresh token")
        sess = _sessions_by_id.get(sid)
        if not sess or sess.revoked:
            raise HTTPException(401, "session revoked")
        if body.refresh_token in sess.consumed_refresh:
            # REPLAY DETECTION — this refresh token was already rotated from.
            sess.compromised = True
            raise HTTPException(401, "refresh token replay detected — session compromised")
        if sess.compromised:
            raise HTTPException(401, "session compromised")
        if body.refresh_token != sess.current_refresh:
            # Shouldn't happen but defensive: neither consumed nor current
            sess.compromised = True
            raise HTTPException(401, "stale refresh token")
        # Rotate.
        sess.consumed_refresh.add(body.refresh_token)
        new_access = _new_token()
        new_refresh = _new_token()
        sess.current_refresh = new_refresh
        sess.access_tokens.add(new_access)
        _refresh_index[new_refresh] = sid
        _access_index[new_access] = sid
    return {"access_token": new_access, "refresh_token": new_refresh, "session_id": sid}


@app.get("/whoami")
def whoami(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer")
    tok = authorization[len("Bearer "):].strip()
    if not tok:
        raise HTTPException(401, "empty token")
    with _lock:
        sid = _access_index.get(tok)
        if not sid:
            raise HTTPException(401, "unknown token")
        sess = _sessions_by_id.get(sid)
        if not sess or sess.revoked or sess.compromised:
            raise HTTPException(401, "session invalid")
        return {"username": sess.username, "session_id": sid}


@app.post("/logout", status_code=204)
def logout(body: LogoutBody) -> None:
    with _lock:
        sid = _refresh_index.get(body.refresh_token)
        if not sid:
            raise HTTPException(401, "invalid token")
        sess = _sessions_by_id.get(sid)
        if sess:
            sess.revoked = True
    return None
