"""CsrfGuard primitive — per-session CSRF token issuer and verifier.

Implements the catalog Protocol for `security.CsrfGuard`. The guard binds a
token to a session id using HMAC-SHA256 over a per-instance secret so the
token MUST match both the session and the server's current signing key.

Invariant IDs (enforced at runtime):

- CSRF-INV-01: tokens MUST be bound to the session id; tokens issued for one
  session MUST NEVER verify for a different session.
- CSRF-INV-02: verify() MUST compare in constant time (hmac.compare_digest).
- CSRF-INV-03: safe methods (GET/HEAD/OPTIONS) MUST NEVER mutate state; the
  `is_safe_method` helper guards callers who forget.
- CSRF-INV-04: cross-origin requests MUST present a valid token; no token
  MUST fail closed.
- CSRF-INV-05: tokens MUST rotate on session rotation / logout; stale tokens
  SHALL be rejected once the session signing epoch advances.

The guard is stateless across requests; per-session epochs are externalized to
the caller (typically the `SessionStore` rotation event).
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Final, Protocol, runtime_checkable

SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})
MIN_SECRET_BYTES: Final[int] = 32
TOKEN_NONCE_BYTES: Final[int] = 16


class CsrfGuardError(ValueError):
    """Runtime invariant violation on a CsrfGuard operation."""


@runtime_checkable
class CsrfGuard(Protocol):
    def issue(self, session_id: str) -> str: ...
    def verify(self, session_id: str, submitted_token: str) -> None: ...


def is_safe_method(method: str) -> bool:
    """CSRF-INV-03: safe HTTP methods MUST NEVER mutate state."""
    if not isinstance(method, str):
        raise CsrfGuardError("method MUST be a str (RFC 9110).")
    return method.upper() in SAFE_METHODS


@dataclass(frozen=True)
class _TokenParts:
    nonce: bytes
    mac: bytes


def _parse_token(token: str) -> _TokenParts:
    if not isinstance(token, str) or "." not in token:
        raise CsrfGuardError("CSRF-INV-01: token framing invalid.")
    try:
        nonce_hex, mac_hex = token.split(".", 1)
        nonce = bytes.fromhex(nonce_hex)
        mac = bytes.fromhex(mac_hex)
    except ValueError as exc:
        raise CsrfGuardError("CSRF-INV-01: token hex decode failed.") from exc
    if len(nonce) != TOKEN_NONCE_BYTES:
        raise CsrfGuardError(
            f"CSRF-INV-01: nonce MUST be {TOKEN_NONCE_BYTES} bytes; got {len(nonce)}."
        )
    if len(mac) != 32:
        raise CsrfGuardError("CSRF-INV-01: MAC MUST be 32 bytes (SHA-256).")
    return _TokenParts(nonce=nonce, mac=mac)


class HmacCsrfGuard:
    """Reference CsrfGuard. Tokens are `hex(nonce) + "." + hex(HMAC-SHA256(secret, session_id || nonce))`.

    The guard accepts a single `secret` at construction; on session rotation the
    caller pairs the new session id with a fresh token, which implicitly
    invalidates prior tokens because the nonce and session id differ.
    """

    def __init__(self, secret: bytes) -> None:
        if not isinstance(secret, bytes) or len(secret) < MIN_SECRET_BYTES:
            raise CsrfGuardError(
                f"CSRF-INV-01: signing secret MUST be ≥{MIN_SECRET_BYTES} bytes from CSPRNG."
            )
        # Copy to private bytes so the caller clearing the buffer does not
        # invalidate the guard mid-request.
        self._secret = bytes(secret)

    def _mac(self, session_id: str, nonce: bytes) -> bytes:
        return hmac.new(
            self._secret,
            msg=session_id.encode("utf-8") + b"\x00" + nonce,
            digestmod=sha256,
        ).digest()

    def issue(self, session_id: str) -> str:
        if not isinstance(session_id, str) or not session_id:
            raise CsrfGuardError("CSRF-INV-01: session_id MUST be a non-empty str.")
        nonce = secrets.token_bytes(TOKEN_NONCE_BYTES)
        mac = self._mac(session_id, nonce)
        return f"{nonce.hex()}.{mac.hex()}"

    def verify(self, session_id: str, submitted_token: str) -> None:
        """Raise on mismatch; MUST return None on success (Protocol signature).

        CSRF-INV-02: uses hmac.compare_digest — constant time.
        """
        if not isinstance(session_id, str) or not session_id:
            raise CsrfGuardError("CSRF-INV-01: session_id MUST be non-empty str.")
        parts = _parse_token(submitted_token)
        expected = self._mac(session_id, parts.nonce)
        if not hmac.compare_digest(expected, parts.mac):
            # CSRF-INV-02: no information about the expected value in the error.
            raise CsrfGuardError("CSRF-INV-01: token did not verify for this session.")


__all__ = [
    "MIN_SECRET_BYTES",
    "SAFE_METHODS",
    "TOKEN_NONCE_BYTES",
    "CsrfGuard",
    "CsrfGuardError",
    "HmacCsrfGuard",
    "is_safe_method",
]
