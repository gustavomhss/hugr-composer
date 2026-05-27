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

PLAN → SCOPE TIERS
==================
Each subscription plan maps to a fixed scope set that the MCP gate uses to
restrict access to premium tools. The mapping is:

  free        → ["hugr:tools:base"]
                Base tier: access to the free subset of HuGR tools only.

  pro         → ["hugr:tools"]
                Standard tier: full access to the public HuGR tool catalogue.
                Backward-compatible — this was the previous default scope.

  team        → ["hugr:tools", "hugr:org"]
                Adds org-level features: shared workspaces, team management.

  enterprise  → ["hugr:tools", "hugr:org", "hugr:private"]
                Adds private/on-prem tool registries and SSO-gated resources.

Scope derivation rules:
- mint_license(..., scopes=None)  → plan tier drives the scope list (default).
- mint_license(..., scopes=[...]) → explicit list is used as-is (override).
- Unknown plan → LicenseError (fail-closed). Do NOT silently fall back to a
  wider scope; unknown plans must be an explicit mistake on the issuing side.
"""

from __future__ import annotations

import base64
import hmac
import json
import secrets
import time
from hashlib import sha256

_MIN_SECRET_BYTES = 32

# ---------------------------------------------------------------------------
# Plan → scope mapping (authoritative definition; gate reads scopes from JWT)
# ---------------------------------------------------------------------------
#
# Add new plans here only; do NOT remove or rename existing keys because live
# tokens carry the plan name verbatim and must round-trip through introspect.
PLAN_SCOPES: dict[str, list[str]] = {
    "free":       ["hugr:tools:base"],
    "pro":        ["hugr:tools"],                              # backward-compat default
    "team":       ["hugr:tools", "hugr:org"],
    "enterprise": ["hugr:tools", "hugr:org", "hugr:private"],
}

KNOWN_PLANS: frozenset[str] = frozenset(PLAN_SCOPES)


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
    """Issue a signed license key for *seat*, valid for *ttl_seconds*.

    Scope resolution (in priority order):
    1. Explicit *scopes* list → used verbatim.
    2. No *scopes* → derived from *plan* via PLAN_SCOPES.
    3. Unknown *plan* with no *scopes* → LicenseError (fail-closed).
    """
    _check_secret(secret)
    if not seat:
        raise LicenseError("seat must be non-empty")
    if scopes is not None:
        resolved_scopes = list(scopes)
    else:
        if plan not in KNOWN_PLANS:
            raise LicenseError(
                f"unknown plan {plan!r}; valid plans: {sorted(KNOWN_PLANS)}"
            )
        resolved_scopes = list(PLAN_SCOPES[plan])
    payload = {
        "jti": secrets.token_hex(8),  # unique key id, so a single key can be revoked
        "seat": seat,
        "plan": plan,
        "scopes": resolved_scopes,
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
