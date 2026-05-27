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

import os

from fastapi import FastAPI
from pydantic import BaseModel

from hugr_auth.license import introspect_license


class IntrospectRequest(BaseModel):
    key: str


class IntrospectResponse(BaseModel):
    active: bool
    claims: dict | None = None


def _signing_secret() -> bytes:
    """Load the HuGR signing secret from env (hex). Fail-closed if unset."""
    raw = os.getenv("HUGR_LICENSE_SIGNING_SECRET", "")
    if not raw:
        return b""  # no secret configured → introspection denies everything
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return raw.encode("utf-8")


app = FastAPI(title="HuGR Auth", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/introspect", response_model=IntrospectResponse)
def introspect(req: IntrospectRequest) -> IntrospectResponse:
    """Verify a license key. Active+claims when valid, inactive otherwise.

    Fail-closed: a missing/short secret or any verification failure → inactive.
    """
    secret = _signing_secret()
    if len(secret) < 32:
        return IntrospectResponse(active=False)
    claims = introspect_license(secret, req.key)
    if claims is None:
        return IntrospectResponse(active=False)
    return IntrospectResponse(active=True, claims=claims)
