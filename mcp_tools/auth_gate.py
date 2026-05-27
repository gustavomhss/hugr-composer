"""HuGR subscription gate for the MCP server.

The product model (see PRODUCT/business-model): the value — the ~146 composable
tools — is served by a **HuGR-hosted** MCP server. A client connects over HTTP
with a HuGR license key as a bearer token. Without a valid subscription the
server authenticates nobody, so it exposes nothing. This is the only gate that
survives a determined user: the tool *code* never reaches their disk, so there
is nothing to copy and no local check to delete.

This module provides the FastMCP `TokenVerifier` that enforces that gate. It is
inert unless the gate is explicitly enabled (``HUGR_GATE``), so the default
local/stdio developer and OSS flows are unchanged.

Wiring (in mcp_tools/server.py / mcp_server.py):
    auth = HugrTokenVerifier() if gate_enabled() else None
    mcp = FastMCP(..., auth=auth)
    # and, when gated, serve over HTTP so the bearer token can ride:
    mcp.run(transport="http", host=..., port=...)

The license-validation SEAM is `_validate_license`. Today it is a fail-closed
stub: it accepts only keys explicitly configured for dev/test and otherwise
denies. The production implementation replaces the stub body with a call to the
HuGR auth API (verify subscription active + resolve the seat's plan/scopes).
"""

from __future__ import annotations

import os
import time

from fastmcp.server.auth.auth import AccessToken, TokenVerifier

# Scopes a paid seat carries. Kept trivial for now; the real plan tiers
# (pro / team / enterprise) map to scope sets resolved by the HuGR auth API.
_DEFAULT_SCOPES = ["hugr:tools"]


def gate_enabled() -> bool:
    """True when the subscription gate should be enforced.

    Off by default so local stdio / OSS / test flows keep working untouched.
    """
    return os.getenv("HUGR_GATE", "").strip().lower() in ("1", "true", "yes", "on")


def _dev_license_keys() -> set[str]:
    """Keys accepted by the dev/test stub (comma-separated in HUGR_DEV_LICENSE_KEYS)."""
    raw = os.getenv("HUGR_DEV_LICENSE_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def _introspect_remote(base_url: str, token: str) -> dict | None:
    """POST the key to the HuGR auth service's /introspect; return claims or None.

    Fail-closed: any transport error, non-200, or inactive verdict → None, so a
    flaky/unreachable auth service denies rather than leaks. Factored out so the
    HTTP edge is mockable in tests.
    """
    import httpx

    try:
        resp = httpx.post(
            f"{base_url.rstrip('/')}/introspect",
            json={"key": token},
            timeout=5.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    data = resp.json()
    return data.get("claims") if data.get("active") else None


def _validate_license(token: str) -> dict | None:
    """Validate a license key; return the seat's claims if active, else None.

    Resolution order:
    1. **HuGR auth API** (when ``HUGR_AUTH_URL`` is set) — the real authority:
       POST the opaque key to ``/introspect``; only the service holds the
       signing secret. This is the production path.
    2. **Dev keys** (``HUGR_DEV_LICENSE_KEYS``) — local/CI shortcut when no auth
       service is configured.
    3. Otherwise **deny** — an enabled gate never leaks tools by accident.
    """
    if not token:
        return None

    auth_url = os.getenv("HUGR_AUTH_URL", "").strip()
    if auth_url:
        return _introspect_remote(auth_url, token)

    if token in _dev_license_keys():
        return {
            "client_id": f"dev:{token[:8]}",
            "scopes": list(_DEFAULT_SCOPES),
            "plan": "dev",
        }
    return None


class HugrTokenVerifier(TokenVerifier):
    """FastMCP token verifier backed by the HuGR subscription check.

    Returns an :class:`AccessToken` for a valid, active license key and ``None``
    for anything else — which FastMCP turns into an auth failure, leaving the
    unlicensed client with zero usable tools.
    """

    def __init__(self, *, required_scopes: list[str] | None = None) -> None:
        super().__init__(required_scopes=required_scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = _validate_license(token)
        if claims is None:
            return None

        scopes = claims.get("scopes", list(_DEFAULT_SCOPES))
        if self.required_scopes and not set(self.required_scopes).issubset(set(scopes)):
            return None

        return AccessToken(
            token=token,
            client_id=claims.get("client_id", "hugr"),
            scopes=scopes,
            expires_at=claims.get("expires_at"),
            claims=claims,
        )
