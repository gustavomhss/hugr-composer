"""HuGR auth service — minimal FastAPI exposing license introspection.

The MCP gate POSTs an opaque license key to ``/introspect``; this service (the
only holder of the signing secret) verifies it and returns whether the seat is
active plus its claims. Thin glue over hugr_auth.license — all logic lives in
the framework-free core.

Run (dev)::

    HUGR_LICENSE_SIGNING_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))") \
      uvicorn hugr_auth.app:app --port 8079

The signing secret comes from HUGR_LICENSE_SIGNING_SECRET (hex). The MCP gate
points at this service via HUGR_AUTH_URL.
"""

from __future__ import annotations

import hmac
import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from hugr_auth.store import (
    FileSubscriptionStore,
    InMemorySubscriptionStore,
    SubscriptionStore,
    authorize,
)


class IntrospectRequest(BaseModel):
    key: str


class IntrospectResponse(BaseModel):
    active: bool
    claims: dict | None = None


class SeatRequest(BaseModel):
    seat: str


class KeyRequest(BaseModel):
    jti: str


def _signing_secret() -> bytes:
    """Load the HuGR signing secret from env (hex). Fail-closed if unset."""
    raw = os.getenv("HUGR_LICENSE_SIGNING_SECRET", "")
    if not raw:
        return b""  # no secret configured → introspection denies everything
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


def _build_store() -> SubscriptionStore:
    """File-backed deny-list when HUGR_STORE_PATH is set, else in-memory."""
    path = os.getenv("HUGR_STORE_PATH", "").strip()
    return FileSubscriptionStore(path) if path else InMemorySubscriptionStore()


app = FastAPI(title="HuGR Auth", version="0.1.0")
# Single process-wide store. Module-level so tests can mutate it directly; the
# admin endpoints below are the HTTP path the billing flow uses.
store: SubscriptionStore = _build_store()


def _require_admin(authorization: str | None) -> None:
    """Fail-closed admin guard: requires Bearer == HUGR_ADMIN_TOKEN (>= 16 chars)."""
    expected = os.getenv("HUGR_ADMIN_TOKEN", "")
    presented = (authorization or "").removeprefix("Bearer ").strip()
    if len(expected) < 16 or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=403, detail="admin auth required")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/introspect", response_model=IntrospectResponse)
def introspect(req: IntrospectRequest) -> IntrospectResponse:
    """Authentic AND entitled → active+claims, else inactive.

    Fail-closed: missing/short secret, bad signature, expiry, a cancelled seat
    or a revoked key all yield inactive.
    """
    secret = _signing_secret()
    if len(secret) < 32:
        return IntrospectResponse(active=False)
    claims = authorize(secret, req.key, store)
    if claims is None:
        return IntrospectResponse(active=False)
    return IntrospectResponse(active=True, claims=claims)


@app.post("/admin/cancel_seat")
def admin_cancel_seat(req: SeatRequest, authorization: str | None = Header(default=None)) -> dict:
    """Cancel a seat — every key it holds is denied on the next introspection."""
    _require_admin(authorization)
    store.cancel_seat(req.seat)  # type: ignore[attr-defined]
    return {"seat": req.seat, "cancelled": True}


@app.post("/admin/revoke_key")
def admin_revoke_key(req: KeyRequest, authorization: str | None = Header(default=None)) -> dict:
    """Revoke a single key by jti (e.g. a leaked key) without cancelling the seat."""
    _require_admin(authorization)
    store.revoke_key(req.jti)  # type: ignore[attr-defined]
    return {"jti": req.jti, "revoked": True}
