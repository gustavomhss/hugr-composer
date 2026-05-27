"""Framework-free license token core: mint + introspect.

A HuGR license key is a compact HMAC-signed token::

    <payload>.<sig>

where ``payload`` is url-safe-base64 JSON ``{seat, plan, scopes, exp}`` and
``sig`` is HMAC-SHA256(payload) under the HuGR signing secret. Only the auth
service holds the secret, so only it can mint or verify — the client (the MCP
gate) just relays the opaque key.

Signing gives offline-verifiable integrity + a hard expiry; the introspection
*endpoint* (app.py) adds real-time authority (a cancelled seat can be denied
before exp via a denylist — a later brick). No database needed for this first
cut: validity = good signature AND not expired.

INVARIANTS
- LIC-INV-01: a tampered payload or signature MUST NOT verify (constant-time
  compare; any mismatch → None).
- LIC-INV-02: an expired token (exp <= now) MUST NOT verify.
- LIC-INV-03: secrets are >= 32 bytes; minting/verifying never logs the secret.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

_MIN_SECRET_BYTES = 32


class LicenseError(ValueError):
    """Invalid input to mint/introspect (e.g. weak secret)."""


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(secret: bytes, body: str) -> str:
    return _b64u_encode(hmac.new(secret, body.encode("ascii"), sha256).digest())


def _check_secret(secret: bytes) -> None:
    if not isinstance(secret, (bytes, bytearray)) or len(secret) < _MIN_SECRET_BYTES:
        raise LicenseError(
            f"LIC-INV-03: signing secret must be >= {_MIN_SECRET_BYTES} bytes"
        )


def mint_license(
    secret: bytes,
    *,
    seat: str,
    plan: str = "pro",
    scopes: list[str] | None = None,
    ttl_seconds: int = 30 * 24 * 3600,
    now: float | None = None,
) -> str:
    """Issue a signed license key for *seat*, valid for *ttl_seconds*."""
    _check_secret(secret)
    if not seat:
        raise LicenseError("seat must be non-empty")
    payload = {
        "jti": secrets.token_hex(8),  # unique key id, so a single key can be revoked
        "seat": seat,
        "plan": plan,
        "scopes": list(scopes or ["hugr:tools"]),
        "exp": int((now if now is not None else time.time()) + ttl_seconds),
    }
    body = _b64u_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{body}.{_sign(secret, body)}"


def introspect_license(
    secret: bytes,
    key: str,
    *,
    now: float | None = None,
) -> dict | None:
    """Verify a license key; return its claims if valid+active, else None.

    Claims shape matches what the MCP gate's AccessToken needs:
    ``{client_id, plan, scopes, expires_at}``.
    """
    _check_secret(secret)
    if not key or "." not in key:
        return None
    body, sig = key.rsplit(".", 1)

    # LIC-INV-01: constant-time signature check.
    if not hmac.compare_digest(sig, _sign(secret, body)):
        return None

    try:
        payload = json.loads(_b64u_decode(body))
    except (ValueError, json.JSONDecodeError):
        return None

    exp = payload.get("exp")
    if not isinstance(exp, int):
        return None
    # LIC-INV-02: reject expired.
    if exp <= int(now if now is not None else time.time()):
        return None

    return {
        "client_id": payload.get("seat", "hugr"),
        "seat": payload.get("seat", "hugr"),
        "jti": payload.get("jti", ""),
        "plan": payload.get("plan", "pro"),
        "scopes": list(payload.get("scopes", ["hugr:tools"])),
        "expires_at": exp,
    }
