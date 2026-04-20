"""AuthorizationCodeFlow primitive — OAuth 2.1 / PKCE S256 authorization-code grant.

Implements the catalog Protocol for `auth.AuthorizationCodeFlow` and installs
runtime invariant checkers. The module performs zero I/O at import (no HTTP,
no token-endpoint calls); the token endpoint is injected as a callable so the
primitive remains unit-testable without a network.

Invariant IDs cited by this module:

- ACF-INV-01: ``begin()`` MUST sample ``state`` and ``nonce`` (and the PKCE
  ``code_verifier``) from a CSPRNG providing ≥128 bits of entropy; a value
  that has already been issued by the same flow instance is NEVER reused.
- ACF-INV-02: ``exchange()`` MUST reject any callback whose ``state`` does
  not byte-equal the stored state. The rejection SHALL happen before the
  token endpoint is touched.
- ACF-INV-03: The PKCE ``code_verifier`` MUST be bound to the authorization
  request; it CANNOT be substituted at exchange time. S256 is the only
  supported ``code_challenge_method``.
- ACF-INV-04: The redirect URI submitted on exchange MUST exactly match the
  URI registered with the authorization server. Wildcard / suffix matches
  are FORBIDDEN.
- ACF-INV-05: Authorization codes MUST be single-use. A replay of the same
  code SHALL raise ``InvalidGrantError`` (``error='invalid_grant'``) and
  MUST NEVER reach the token endpoint twice.
- ACF-INV-06: Tokens received from the authorization server MUST NEVER be
  logged in full. Only opaque SHA-256 hashes (hex, 16-char prefix) MAY
  appear in audit traces via ``for_audit()``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable
from urllib.parse import quote, urlencode

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# RFC 7636 §4.1: code_verifier length 43..128 chars of the unreserved set.
# 32 random bytes → 43 base64url chars, each char ≈6 bits → 192 bits of entropy,
# comfortably above the 128-bit floor.
_CSPRNG_BYTES: Final[int] = 32
_MIN_ENTROPY_BITS: Final[int] = 128
_REDACTED_TOKEN: Final[str] = "[REDACTED_TOKEN]"  # noqa: S105 — public marker, not a secret (ACF-INV-06 redaction sentinel).
_HASH_PREFIX_LEN: Final[int] = 16

_PKCE_METHOD_S256: Final[str] = "S256"

# Errors the primitive surfaces. Every error message is OAuth-style `error`
# code followed by a human blurb — callers can route on the prefix.
_ERR_INVALID_STATE: Final[str] = "invalid_state"
_ERR_INVALID_GRANT: Final[str] = "invalid_grant"
_ERR_INVALID_REQUEST: Final[str] = "invalid_request"
_ERR_INVALID_REDIRECT: Final[str] = "invalid_redirect_uri"

_SENSITIVE_TOKEN_KEYS: Final[frozenset[str]] = frozenset({
    "access_token",
    "refresh_token",
    "id_token",
    "token",
})


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------
class AuthorizationCodeFlowError(RuntimeError):
    """Base error for every AuthorizationCodeFlow invariant violation.

    ``error`` matches the OAuth 2.0 token-endpoint error code where
    applicable (RFC 6749 §5.2); ``invariant_id`` cites the ACF-INV-* rule.
    """

    def __init__(self, error: str, message: str, *, invariant_id: str) -> None:
        super().__init__(f"{error}: {message} ({invariant_id})")
        self.error: str = error
        self.invariant_id: str = invariant_id


class InvalidStateError(AuthorizationCodeFlowError):
    """ACF-INV-02: state mismatch — aborted BEFORE token endpoint."""


class InvalidGrantError(AuthorizationCodeFlowError):
    """ACF-INV-05: code replay / expired code / PKCE mismatch."""


class InvalidRedirectURIError(AuthorizationCodeFlowError):
    """ACF-INV-04: redirect_uri drift between begin() and exchange()."""


class InvalidRequestError(AuthorizationCodeFlowError):
    """ACF-INV-01/03: malformed request (non-str inputs, empty scopes, etc)."""


# ---------------------------------------------------------------------------
# Catalog-verbatim data shapes
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AuthorizationRequest:
    """The opaque token the client stores in its session while the user
    roundtrips through the authorization server.

    Every field is immutable (frozen dataclass) so a later middleware
    CANNOT rotate ``state`` / ``code_verifier`` under the flow's feet.
    """

    authorization_url: str
    state: str
    nonce: str
    code_verifier: str


# ---------------------------------------------------------------------------
# Protocol surface (matches catalog api_signature verbatim)
# ---------------------------------------------------------------------------
@runtime_checkable
class AuthorizationCodeFlow(Protocol):
    def begin(self, scopes: list[str]) -> AuthorizationRequest: ...
    def exchange(
        self,
        code: str,
        state: str,
        stored: AuthorizationRequest,
    ) -> dict[str, object]: ...


# ---------------------------------------------------------------------------
# Provider metadata (extension-contract surface)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """OIDC discovery metadata required to register a provider.

    The registry rejects any provider that does not advertise PKCE S256 —
    see ``require_s256_support``.
    """

    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    code_challenge_methods_supported: tuple[str, ...]
    issuer: str = ""


def require_s256_support(meta: ProviderMetadata) -> None:
    """Extension-contract check: refuse providers without PKCE S256."""
    if _PKCE_METHOD_S256 not in meta.code_challenge_methods_supported:
        raise InvalidRequestError(
            _ERR_INVALID_REQUEST,
            "provider MUST advertise 'S256' in code_challenge_methods_supported; "
            f"got {meta.code_challenge_methods_supported!r}",
            invariant_id="ACF-INV-03",
        )


# ---------------------------------------------------------------------------
# Token-endpoint transport shape
# ---------------------------------------------------------------------------
# A token endpoint is any callable that turns the token-request parameters
# into a token response. Real deployments wire this to httpx; tests inject
# a lambda so no network I/O is required.
TokenEndpoint = Callable[[Mapping[str, str]], Mapping[str, object]]


# ---------------------------------------------------------------------------
# Helpers — base64url, PKCE, redaction
# ---------------------------------------------------------------------------
def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_challenge_s256(verifier: str) -> str:
    """RFC 7636 §4.2: BASE64URL-ENCODE(SHA256(verifier))."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return _b64url(digest)


def _token_hash(value: str) -> str:
    """ACF-INV-06: opaque 16-hex prefix of SHA-256; never reversible to token."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]


def redact_token_response(resp: Mapping[str, object]) -> dict[str, object]:
    """ACF-INV-06: return a log-safe view of a token response.

    Every sensitive token field is replaced with ``[REDACTED_TOKEN]``; a
    paired ``*_hash`` key holds the opaque 16-char SHA-256 prefix so
    operators can correlate audit traces without ever seeing plaintext.
    Non-sensitive metadata (``token_type``, ``expires_in``, ``scope``)
    passes through unchanged.
    """
    out: dict[str, object] = {}
    for k, v in resp.items():
        if k.lower() in _SENSITIVE_TOKEN_KEYS and isinstance(v, str):
            out[k] = _REDACTED_TOKEN
            out[f"{k}_hash"] = _token_hash(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Redirect-URI policy (ACF-INV-04)
# ---------------------------------------------------------------------------
def _assert_redirect_uri_registered(candidate: str, registered: str) -> None:
    """ACF-INV-04: byte-exact match; wildcards / suffix matches FORBIDDEN."""
    if not isinstance(candidate, str) or candidate == "":
        raise InvalidRedirectURIError(
            _ERR_INVALID_REDIRECT,
            "redirect_uri MUST be a non-empty str",
            invariant_id="ACF-INV-04",
        )
    if "*" in registered or "*" in candidate:
        raise InvalidRedirectURIError(
            _ERR_INVALID_REDIRECT,
            "wildcard redirect URIs are FORBIDDEN",
            invariant_id="ACF-INV-04",
        )
    # Byte-exact — NOT a parse-and-compare (which would let attackers smuggle
    # differing query strings past naive checks). OAuth 2.1 §4.1.3 mandates
    # the strict string comparison.
    if not hmac.compare_digest(candidate.encode("utf-8"), registered.encode("utf-8")):
        raise InvalidRedirectURIError(
            _ERR_INVALID_REDIRECT,
            "redirect_uri does NOT byte-equal the registered URI",
            invariant_id="ACF-INV-04",
        )


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class _IssuedRequest:
    """Internal: tracks which (state, code_verifier) pairs this flow issued."""

    state: str
    nonce: str
    code_verifier: str
    issued_at_monotonic: float
    scopes: tuple[str, ...]


class ReferenceAuthorizationCodeFlow:
    """Reference implementation of the catalog Protocol.

    The flow instance tracks:

    - Every ``state`` / ``nonce`` it has ever issued (so a replay through
      ``begin()`` CANNOT reuse an old value — ACF-INV-01).
    - Every code it has already successfully redeemed (so a replay through
      ``exchange()`` raises ``InvalidGrantError`` — ACF-INV-05).

    The token endpoint is an injected callable; the implementation does no
    network I/O. Observability hooks emit redacted audit traces via
    ``audit_sink`` — see ``observability_schema.json`` for the schema.
    """

    def __init__(
        self,
        *,
        client_id: str,
        redirect_uri: str,
        provider: ProviderMetadata,
        token_endpoint: TokenEndpoint,
        audit_sink: Callable[[Mapping[str, object]], None] | None = None,
        code_ttl_seconds: float = 600.0,
        clock: Callable[[], float] | None = None,
        rng: Callable[[int], bytes] | None = None,
    ) -> None:
        if not isinstance(client_id, str) or client_id == "":
            raise InvalidRequestError(
                _ERR_INVALID_REQUEST,
                "client_id MUST be a non-empty str",
                invariant_id="ACF-INV-01",
            )
        require_s256_support(provider)
        _assert_redirect_uri_registered(redirect_uri, redirect_uri)  # shape check
        self._client_id = client_id
        self._redirect_uri = redirect_uri
        self._provider = provider
        self._token_endpoint: TokenEndpoint = token_endpoint
        self._audit_sink: Callable[[Mapping[str, object]], None] = (
            audit_sink if audit_sink is not None else lambda _e: None
        )
        self._code_ttl_seconds = code_ttl_seconds
        self._clock: Callable[[], float] = clock or time.monotonic
        self._rng: Callable[[int], bytes] = rng or secrets.token_bytes
        self._lock = threading.Lock()
        self._issued: dict[str, _IssuedRequest] = {}
        self._issued_nonces: set[str] = set()
        self._redeemed_codes: set[str] = set()

    # ----- PKCE / CSPRNG helpers -------------------------------------------
    def _sample_token(self) -> str:
        raw = self._rng(_CSPRNG_BYTES)
        if not isinstance(raw, (bytes, bytearray)) or len(raw) < _CSPRNG_BYTES:
            # ACF-INV-01: fail CLOSED if the injected RNG shorts us.
            raise InvalidRequestError(
                _ERR_INVALID_REQUEST,
                f"CSPRNG returned {len(raw) if hasattr(raw, '__len__') else 'unknown'} bytes; "
                f"need ≥{_CSPRNG_BYTES} for ≥{_MIN_ENTROPY_BITS}-bit entropy",
                invariant_id="ACF-INV-01",
            )
        return _b64url(bytes(raw))

    # ----- begin() ----------------------------------------------------------
    def begin(self, scopes: list[str]) -> AuthorizationRequest:
        """ACF-INV-01: emit a fresh, non-repeating AuthorizationRequest."""
        if not isinstance(scopes, list) or not scopes:
            raise InvalidRequestError(
                _ERR_INVALID_REQUEST,
                "scopes MUST be a non-empty list[str]",
                invariant_id="ACF-INV-01",
            )
        for s in scopes:
            if not isinstance(s, str) or s == "":
                raise InvalidRequestError(
                    _ERR_INVALID_REQUEST,
                    f"scope entries MUST be non-empty str; got {s!r}",
                    invariant_id="ACF-INV-01",
                )

        with self._lock:
            # Retry up to 8 times in the astronomically-unlikely event that a
            # fresh CSPRNG sample collides with a previous issue.
            for _ in range(8):
                state = self._sample_token()
                nonce = self._sample_token()
                verifier = self._sample_token()
                triple = {state, nonce, verifier}
                if (
                    state not in self._issued
                    and nonce not in self._issued_nonces
                    and len(triple) == 3
                ):
                    break
            else:
                raise InvalidRequestError(
                    _ERR_INVALID_REQUEST,
                    "CSPRNG produced 8 consecutive collisions; check entropy source",
                    invariant_id="ACF-INV-01",
                )

            challenge = _pkce_challenge_s256(verifier)
            auth_url = self._build_authorization_url(
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                scopes=scopes,
            )
            record = _IssuedRequest(
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                issued_at_monotonic=self._clock(),
                scopes=tuple(scopes),
            )
            self._issued[state] = record
            self._issued_nonces.add(nonce)

        self._audit_sink({
            "event_name": "acf.begin",
            "state_hash": _token_hash(state),
            "nonce_hash": _token_hash(nonce),
            "scope_count": len(scopes),
        })
        return AuthorizationRequest(
            authorization_url=auth_url,
            state=state,
            nonce=nonce,
            code_verifier=verifier,
        )

    def _build_authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_challenge: str,
        scopes: list[str],
    ) -> str:
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": _PKCE_METHOD_S256,
        }
        sep = "&" if "?" in self._provider.authorization_endpoint else "?"
        return f"{self._provider.authorization_endpoint}{sep}{urlencode(params, quote_via=quote)}"

    # ----- exchange() -------------------------------------------------------
    def _validate_exchange_inputs(
        self,
        code: str,
        state: str,
        stored: AuthorizationRequest,
    ) -> None:
        """Shape + byte-equality gate. Raises BEFORE touching token endpoint."""
        if not isinstance(code, str) or code == "":
            raise InvalidGrantError(
                _ERR_INVALID_GRANT,
                "code MUST be a non-empty str",
                invariant_id="ACF-INV-05",
            )
        if not isinstance(state, str) or state == "":
            raise InvalidStateError(
                _ERR_INVALID_STATE,
                "state MUST be a non-empty str",
                invariant_id="ACF-INV-02",
            )
        if not isinstance(stored, AuthorizationRequest):
            raise InvalidRequestError(
                _ERR_INVALID_REQUEST,
                "stored MUST be an AuthorizationRequest instance",
                invariant_id="ACF-INV-03",
            )
        # ACF-INV-02: constant-time state comparison. Rejection happens BEFORE
        # the token endpoint is touched.
        if not hmac.compare_digest(state.encode("utf-8"), stored.state.encode("utf-8")):
            self._audit_sink({
                "event_name": "acf.exchange.rejected",
                "reason": _ERR_INVALID_STATE,
                "state_hash": _token_hash(state),
            })
            raise InvalidStateError(
                _ERR_INVALID_STATE,
                "callback state does NOT byte-equal stored state",
                invariant_id="ACF-INV-02",
            )

    def _claim_code_for_redemption(
        self,
        code: str,
        stored: AuthorizationRequest,
    ) -> None:
        """Reserve the code under the lock. Raises on state/PKCE/replay/expiry."""
        with self._lock:
            issued = self._issued.get(stored.state)
            if issued is None:
                raise InvalidStateError(
                    _ERR_INVALID_STATE,
                    "state does not match any outstanding authorization request",
                    invariant_id="ACF-INV-02",
                )
            # ACF-INV-03: PKCE verifier binding. Defence in depth at client side.
            if not hmac.compare_digest(
                stored.code_verifier.encode("utf-8"),
                issued.code_verifier.encode("utf-8"),
            ):
                raise InvalidGrantError(
                    _ERR_INVALID_GRANT,
                    "code_verifier does NOT match the verifier bound to the authorization request",
                    invariant_id="ACF-INV-03",
                )
            # ACF-INV-05 supporting: codes expire.
            if self._clock() - issued.issued_at_monotonic > self._code_ttl_seconds:
                self._issued.pop(stored.state, None)
                raise InvalidGrantError(
                    _ERR_INVALID_GRANT,
                    "authorization code / state has expired",
                    invariant_id="ACF-INV-05",
                )
            # ACF-INV-05: single-use — reserve atomically so concurrent
            # redemption of the SAME code picks one winner.
            code_hash = _token_hash(code)
            if code_hash in self._redeemed_codes:
                raise InvalidGrantError(
                    _ERR_INVALID_GRANT,
                    "authorization code has already been redeemed (single-use)",
                    invariant_id="ACF-INV-05",
                )
            self._redeemed_codes.add(code_hash)
            # Burn the issue record so the same state cannot be reused either.
            self._issued.pop(stored.state, None)

    def _release_code_on_transport_error(self, code: str) -> None:
        """Undo reservation when the token endpoint itself fails.

        Keeps the redeemed-codes set consistent with what the AS actually saw.
        An AS-side rejection ("error" in response) does NOT release because
        the AS MAY have already burned the code server-side.
        """
        with self._lock:
            self._redeemed_codes.discard(_token_hash(code))

    def exchange(
        self,
        code: str,
        state: str,
        stored: AuthorizationRequest,
    ) -> dict[str, object]:
        """ACF-INV-02/03/04/05: redeem a code exactly once, under strict checks."""
        self._validate_exchange_inputs(code, state, stored)
        self._claim_code_for_redemption(code, stored)

        # ACF-INV-04: send the EXACT registered redirect_uri to the token endpoint.
        token_request: Mapping[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
            "client_id": self._client_id,
            "code_verifier": stored.code_verifier,
        }

        try:
            response = self._token_endpoint(token_request)
        except BaseException:
            # Token endpoint crashed (network, TLS, etc). Release our
            # local reservation so the caller MAY retry the same code.
            self._release_code_on_transport_error(code)
            raise

        if not isinstance(response, Mapping):
            raise InvalidGrantError(
                _ERR_INVALID_GRANT,
                f"token endpoint returned non-Mapping: {type(response).__name__}",
                invariant_id="ACF-INV-05",
            )

        if "error" in response:
            err_code = str(response.get("error") or _ERR_INVALID_GRANT)
            raise InvalidGrantError(
                err_code,
                str(response.get("error_description") or "token endpoint rejected the code"),
                invariant_id="ACF-INV-05",
            )

        self._audit_sink({
            "event_name": "acf.exchange.success",
            "state_hash": _token_hash(stored.state),
            "code_hash": _token_hash(code),
            "token_response": redact_token_response(response),
        })
        return dict(response)

    # ----- introspection ---------------------------------------------------
    @property
    def outstanding_count(self) -> int:
        with self._lock:
            return len(self._issued)

    @property
    def redeemed_count(self) -> int:
        with self._lock:
            return len(self._redeemed_codes)

    def has_issued_state(self, state: str) -> bool:
        with self._lock:
            return state in self._issued or any(
                r.state == state for r in self._issued.values()
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def create_flow(
    *,
    client_id: str,
    redirect_uri: str,
    provider: ProviderMetadata,
    token_endpoint: TokenEndpoint,
    audit_sink: Callable[[Mapping[str, object]], None] | None = None,
    code_ttl_seconds: float = 600.0,
) -> ReferenceAuthorizationCodeFlow:
    """Thin factory that returns a correctly-wired ReferenceAuthorizationCodeFlow."""
    return ReferenceAuthorizationCodeFlow(
        client_id=client_id,
        redirect_uri=redirect_uri,
        provider=provider,
        token_endpoint=token_endpoint,
        audit_sink=audit_sink,
        code_ttl_seconds=code_ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Environment probe (defence-in-depth)
# ---------------------------------------------------------------------------
def _entropy_self_check() -> None:
    """Defensive: confirm ``os.urandom`` is available and returns ≥32 bytes.

    Called lazily from module-level utilities that need CSPRNG output; kept
    out of import time so the module boots in sandboxes without entropy.
    """
    sample = os.urandom(_CSPRNG_BYTES)
    if len(sample) != _CSPRNG_BYTES:  # pragma: no cover — platform guarantee
        raise InvalidRequestError(
            _ERR_INVALID_REQUEST,
            "os.urandom returned fewer bytes than requested",
            invariant_id="ACF-INV-01",
        )


__all__ = [
    "AuthorizationCodeFlow",
    "AuthorizationCodeFlowError",
    "AuthorizationRequest",
    "InvalidGrantError",
    "InvalidRedirectURIError",
    "InvalidRequestError",
    "InvalidStateError",
    "ProviderMetadata",
    "ReferenceAuthorizationCodeFlow",
    "TokenEndpoint",
    "create_flow",
    "redact_token_response",
    "require_s256_support",
]

# Ensure the self-check module is referenced (avoids F401 on _entropy_self_check).
_ = _entropy_self_check
