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

from hugr_auth.license import introspect_license, mint_license
from hugr_auth.store import (
    FileSubscriptionStore,
    InMemorySubscriptionStore,
    SubscriptionStore,
    authorize,
)


class IntrospectRequest(BaseModel):
    key: str


class IssueRequest(BaseModel):
    seat: str
    plan: str = "pro"
    scopes: list[str] | None = None
    ttl_days: int = 30


class IssueResponse(BaseModel):
    key: str
    jti: str
    seat: str
    plan: str
    expires_at: int


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
    """Pick the revocation store from env, in precedence order.

    1. ``HUGR_STORE_DSN`` — a SQLAlchemy URL (e.g. a Postgres DSN) → the shared
       ``SqlSubscriptionStore``. This is the production backend: revocations
       written by one auth replica are immediately visible to all others.
       Fail-closed: if a DSN is configured but the SQL store cannot be
       constructed (driver/module missing, DB unreachable), we raise rather
       than silently degrade to a process-local store that would lose
       revocations.
    2. ``HUGR_STORE_PATH`` — a JSON file path → ``FileSubscriptionStore``
       (single-instance durable; survives restart).
    3. neither → ``InMemorySubscriptionStore`` (dev/test only; lost on restart).
    """
    dsn = os.getenv("HUGR_STORE_DSN", "").strip()
    if dsn:
        # Lazy import: store_sql (and its SQLAlchemy dep) is only needed for the
        # production SQL backend, so the file/in-memory paths stay dependency-free.
        from hugr_auth.store_sql import SqlSubscriptionStore  # noqa: PLC0415

        return SqlSubscriptionStore(dsn)
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


@app.post("/admin/issue", response_model=IssueResponse)
def admin_issue(req: IssueRequest, authorization: str | None = Header(default=None)) -> IssueResponse:
    """Mint a license key for a seat — what the billing flow calls on subscribe.

    Admin-guarded; fail-closed when no signing secret is configured.
    """
    _require_admin(authorization)
    secret = _signing_secret()
    if len(secret) < 32:
        raise HTTPException(status_code=503, detail="signing secret not configured")
    key = mint_license(
        secret,
        seat=req.seat,
        plan=req.plan,
        scopes=req.scopes,
        ttl_seconds=req.ttl_days * 24 * 3600,
    )
    claims = introspect_license(secret, key) or {}
    return IssueResponse(
        key=key,
        jti=claims.get("jti", ""),
        seat=req.seat,
        plan=req.plan,
        expires_at=claims.get("expires_at", 0),
    )


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
