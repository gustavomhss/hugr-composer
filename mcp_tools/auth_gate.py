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

The license-validation SEAM is `_validate_license`. Production implementation
calls the HuGR auth API (verify subscription active + resolve the seat's
plan/scopes) with fail-open resilience: if the auth service is unreachable,
the request is allowed with a warning.
"""

from __future__ import annotations

import os
import time
import logging
from functools import lru_cache
from typing import Optional

import httpx
from fastmcp.server.auth.auth import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)

# Scopes a paid seat carries. Real plan tiers (pro / team / enterprise) map to
# scope sets resolved by the HuGR auth API.
_DEFAULT_SCOPES = ["hugr:tools"]

# Cache TTL for valid tokens (5 minutes)
_CACHE_TTL_SECONDS = 300

# Introspection endpoint path
_INTROSPECT_PATH = "/v1/tokens/introspect"

# HTTP timeouts: 2s connect, 5s read
_HTTP_TIMEOUT = httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=5.0)


def gate_enabled() -> bool:
    """True when the subscription gate should be enforced.

    Off by default so local stdio / OSS / test flows keep working untouched.
    """
    return os.getenv("HUGR_GATE", "").strip().lower() in ("1", "true", "yes", "on")


def _dev_license_keys() -> set[str]:
    """Keys accepted by the dev/test stub (comma-separated in HUGR_DEV_LICENSE_KEYS)."""
    raw = os.getenv("HUGR_DEV_LICENSE_KEYS", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


class _TokenCache:
    """Simple in-memory cache with TTL for validated tokens.

    Cache keys include the auth_url so that tokens validated against
    different auth configurations don't collide (e.g., dev mode vs
    production mode with HUGR_AUTH_URL).
    """

    def __init__(self, ttl_seconds: int = _CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._cache: dict[tuple[str, str], tuple[dict, float]] = {}

    def _make_key(self, token: str, auth_url: str) -> tuple[str, str]:
        return (token, auth_url)

    def get(self, token: str, auth_url: str) -> Optional[dict]:
        key = self._make_key(token, auth_url)
        if key not in self._cache:
            return None
        claims, expires_at = self._cache[key]
        if time.time() > expires_at:
            del self._cache[key]
            return None
        return claims

    def set(self, token: str, auth_url: str, claims: dict) -> None:
        key = self._make_key(token, auth_url)
        self._cache[key] = (claims, time.time() + self._ttl)

    def clear(self) -> None:
        self._cache.clear()


_token_cache = _TokenCache()


def _normalize_token(token: str) -> str:
    """Normalize token: strip 'Bearer ' prefix if present, handle API key format."""
    token = token.strip()
    if token.lower().startswith("bearer "):
        return token[7:].strip()
    # Support API key format: hugr_<key> or just the key
    if token.startswith("hugr_"):
        return token[5:]
    return token


async def _introspect_remote(base_url: str, token: str) -> dict | None:
    """POST the token to the HuGR auth service's introspection endpoint.

    Contract (defined here):
    - POST {HUGR_AUTH_URL}/v1/tokens/introspect
    - Headers: Authorization: Bearer <token>
    - Response: {active: bool, client_id: str, scopes: list[str], exp: int}

    Returns:
    - dict with claims if token is active
    - None if token is inactive (active: false)
    - Raises httpx.HTTPError / TimeoutException for transport failures,
      non-200 responses, or invalid JSON — caller handles these as fail-open.
    """
    url = f"{base_url.rstrip('/')}{_INTROSPECT_PATH}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(url, headers=headers)
    except httpx.TimeoutException:
        logger.warning(
            "HuGR auth introspection timed out (connect=2s, read=5s); "
            "failing open for resilience. url=%s",
            url,
        )
        raise
    except httpx.HTTPError as e:
        logger.warning(
            "HuGR auth introspection transport error; failing open for resilience. "
            "url=%s error=%s",
            url,
            e,
        )
        raise

    if resp.status_code != 200:
        logger.warning(
            "HuGR auth introspection returned %s; failing open. url=%s body=%s",
            resp.status_code,
            url,
            resp.text[:500],
        )
        raise httpx.HTTPStatusError(
            f"Introspection returned {resp.status_code}",
            request=resp.request,
            response=resp,
        )

    try:
        data = resp.json()
    except ValueError:
        logger.warning(
            "HuGR auth introspection returned invalid JSON; failing open. url=%s",
            url,
        )
        raise httpx.HTTPError("Invalid JSON response from introspection endpoint")

    if not data.get("active", False):
        logger.info("HuGR auth introspection: token inactive. url=%s", url)
        return None

    return {
        "client_id": data.get("client_id", "hugr"),
        "scopes": data.get("scopes", list(_DEFAULT_SCOPES)),
        "plan": data.get("plan", "unknown"),
        "expires_at": data.get("exp"),
    }


async def _validate_license(token: str) -> dict | None:
    """Validate a license key; return the seat's claims if active, else None.

    Resolution order:
    1. **Cache** — return cached claims if fresh (5 min TTL)
    2. **HuGR auth API** (when ``HUGR_AUTH_URL`` is set) — the real authority:
       POST the token to ``/v1/tokens/introspect`` with Bearer auth.
    3. **Dev keys** (``HUGR_DEV_LICENSE_KEYS``) — local/CI shortcut when no auth
       service is configured.
    4. **Fail-open** — if HUGR_GATE=1 but no HUGR_AUTH_URL and no dev keys,
       allow with loud warning (don't break local dev).
       Also: if HUGR_AUTH_URL is set but introspection fails/times out,
       fail-open for resilience (warning already logged by _introspect_remote).

    Async because path (2) does network I/O; paths (1), (3), (4) are CPU-only
    but still ``await``-able so callers have one uniform interface.
    """
    if not token:
        return None

    # Normalize token (strip Bearer prefix, hugr_ prefix)
    normalized_token = _normalize_token(token)

    auth_url = os.getenv("HUGR_AUTH_URL", "").strip()

    # Check cache first (keyed by token + auth_url)
    cached = _token_cache.get(normalized_token, auth_url)
    if cached:
        return cached

    # Path 2: HuGR auth API (when configured)
    if auth_url:
        try:
            claims = await _introspect_remote(auth_url, normalized_token)
        except (httpx.TimeoutException, httpx.HTTPError):
            # Transport failure, timeout, non-200, invalid JSON → fail-open
            # _introspect_remote already logged a warning
            logger.warning(
                "HuGR auth introspection failed for token %s***; failing open for resilience. "
                "Configure a reliable HUGR_AUTH_URL for production.",
                normalized_token[:8] if len(normalized_token) > 8 else "short",
            )
            claims = {
                "client_id": f"fail-open:{normalized_token[:8]}",
                "scopes": list(_DEFAULT_SCOPES),
                "plan": "fail-open",
            }
            _token_cache.set(normalized_token, auth_url, claims)
            return claims

        if claims:
            # Token is active - cache and return
            _token_cache.set(normalized_token, auth_url, claims)
            return claims

        # claims is None → token is inactive (active: false) → DENY
        # Do NOT fail-open for inactive tokens; the auth API explicitly said no.
        # Do NOT fall back to dev keys when HUGR_AUTH_URL is set.
        return None

    # Path 3: Dev keys fallback (only when NO HUGR_AUTH_URL is configured)
    if normalized_token in _dev_license_keys():
        claims = {
            "client_id": f"dev:{normalized_token[:8]}",
            "scopes": list(_DEFAULT_SCOPES),
            "plan": "dev",
        }
        _token_cache.set(normalized_token, auth_url, claims)
        return claims

    # Path 4: Fail-open with loud warning when gate enabled but no auth configured
    if gate_enabled() and not _dev_license_keys():
        logger.warning(
            "HUGR_GATE=1 but HUGR_AUTH_URL not configured and no HUGR_DEV_LICENSE_KEYS set. "
            "Failing OPEN for local development. Configure HUGR_AUTH_URL for production "
            "or HUGR_DEV_LICENSE_KEYS for testing. Token presented: %s***",
            normalized_token[:8] if len(normalized_token) > 8 else "short",
        )
        # Return minimal claims to allow the request through (fail-open)
        claims = {
            "client_id": f"fail-open:{normalized_token[:8]}",
            "scopes": list(_DEFAULT_SCOPES),
            "plan": "fail-open",
        }
        _token_cache.set(normalized_token, auth_url, claims)
        return claims

    # Explicit deny: gate not enabled, or gate enabled with dev keys but token not in dev keys
    return None


class HugrTokenVerifier(TokenVerifier):
    """FastMCP token verifier backed by the HuGR subscription check.

    Returns an :class:`AccessToken` for a valid, active license key and ``None``
    for anything else — which FastMCP turns into an auth failure, leaving the
    unlicensed client with zero usable tools.

    When HUGR_GATE=1 and HUGR_AUTH_URL is not configured, operates in fail-open
    mode with loud warnings to not break local development.
    """

    def __init__(self, *, required_scopes: list[str] | None = None) -> None:
        super().__init__(required_scopes=required_scopes)

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = await _validate_license(token)
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


def clear_token_cache() -> None:
    """Clear the token validation cache. Useful for testing or forced revalidation."""
    _token_cache.clear()
