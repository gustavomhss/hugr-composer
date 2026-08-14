"""TokenIntrospector primitive — RFC 7662 + JWT validation with pinned-algorithm policy.

Implements the catalog Protocol for `auth.TokenIntrospector` and installs
runtime invariant checkers. The module performs zero I/O at import.

Invariant IDs cited by this module:

- TI-INV-01: JWT verification MUST reject the 'none' algorithm and MUST pin
  the accepted algorithm set per issuer.
- TI-INV-02: introspect() MUST reject tokens whose aud claim does not
  include required_audience and SHALL raise a typed error.
- TI-INV-03: Expired tokens (now >= exp) and not-yet-valid tokens (now < nbf)
  MUST be rejected with no claim surface returned.
- TI-INV-04: Signing keys MUST be fetched from the issuer's JWKS with bounded
  caching; stale keys beyond max-age CANNOT be trusted.
- TI-INV-05: Opaque tokens MUST be introspected against the authorization
  server per RFC 7662 and NEVER parsed locally.
- TI-INV-06: Introspection results MUST NEVER be cached past the token's exp
  or past the documented TTL, whichever is lower.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Final, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
FORBIDDEN_ALGORITHMS: Final[frozenset[str]] = frozenset({"none", "None", "NONE"})
DEFAULT_JWKS_MAX_AGE_S: Final[int] = 300
DEFAULT_INTROSPECTION_TTL_S: Final[int] = 60

# RFC 7662 response field name for token status — MUST be honored verbatim.
_RFC7662_ACTIVE: Final[str] = "active"


# ---------------------------------------------------------------------------
# Error type
# ---------------------------------------------------------------------------
class TokenIntrospectorInvariantError(ValueError):
    """Raised when a TokenIntrospector invariant is violated at runtime."""


class InvalidTokenError(TokenIntrospectorInvariantError):
    """Raised when a token fails verification (typed error per TI-INV-02)."""


# ---------------------------------------------------------------------------
# Catalog data shape (verbatim)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class TokenClaims:
    subject: str
    scopes: frozenset[str]
    audience: frozenset[str]
    issuer: str
    expires_at: int


# ---------------------------------------------------------------------------
# Catalog Protocol surface
# ---------------------------------------------------------------------------
@runtime_checkable
class TokenIntrospector(Protocol):
    def introspect(self, token: str, required_audience: str) -> TokenClaims: ...


# ---------------------------------------------------------------------------
# Issuer configuration (TI-INV-01 / TI-INV-04)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IssuerConfig:
    """Pins the accepted algorithm set + JWKS cache policy for one issuer.

    - ``allowed_algorithms``: the non-empty set of JWS algorithms the issuer
      may use. 'none' is rejected at construction per TI-INV-01.
    - ``jwks_max_age_s``: hard upper bound on JWKS cache freshness per
      TI-INV-04. Any cached key older than this MUST be refetched.
    """

    issuer: str
    allowed_algorithms: frozenset[str]
    jwks_max_age_s: int = DEFAULT_JWKS_MAX_AGE_S

    def __post_init__(self) -> None:
        if not isinstance(self.issuer, str) or self.issuer == "":
            raise TokenIntrospectorInvariantError("TI-INV-01: issuer MUST be a non-empty str.")
        if not isinstance(self.allowed_algorithms, frozenset):
            raise TokenIntrospectorInvariantError(
                "TI-INV-01: allowed_algorithms MUST be a frozenset[str] so the "
                "policy CANNOT be mutated at call time."
            )
        if not self.allowed_algorithms:
            raise TokenIntrospectorInvariantError(
                "TI-INV-01: allowed_algorithms MUST be non-empty; pin at least "
                "one algorithm per issuer."
            )
        bad = self.allowed_algorithms & FORBIDDEN_ALGORITHMS
        if bad:
            raise TokenIntrospectorInvariantError(
                "TI-INV-01: the 'none' algorithm is FORBIDDEN; got "
                f"{sorted(bad)!r} in allowed_algorithms for issuer {self.issuer!r}."
            )
        if self.jwks_max_age_s <= 0:
            raise TokenIntrospectorInvariantError(
                f"TI-INV-04: jwks_max_age_s MUST be positive; got {self.jwks_max_age_s}."
            )


# ---------------------------------------------------------------------------
# Key + signing-key fetcher Protocol (TI-INV-04)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SigningKey:
    """One JWKS entry — ``kid`` bound to a raw secret for HS* algorithms.

    The reference implementation uses HS256 for its test harness — real
    deployments plug in an RSA/ECDSA verifier that matches the same shape.
    """

    kid: str
    algorithm: str
    secret: bytes


@runtime_checkable
class JwksFetcher(Protocol):
    """Adapter that resolves an issuer to its current JWKS."""

    def fetch(self, issuer: str) -> list[SigningKey]: ...


# ---------------------------------------------------------------------------
# RFC 7662 introspection endpoint Protocol (TI-INV-05)
# ---------------------------------------------------------------------------
@runtime_checkable
class IntrospectionEndpoint(Protocol):
    """Adapter that calls the authorization server's ``/introspect`` endpoint.

    Returns the raw JSON response dict. Opaque tokens MUST be routed through
    this adapter — never parsed locally (TI-INV-05).
    """

    def introspect(self, token: str) -> Mapping[str, object]: ...


# ---------------------------------------------------------------------------
# Internal clock Protocol — lets tests run deterministically
# ---------------------------------------------------------------------------
Clock = Callable[[], float]


# ---------------------------------------------------------------------------
# JWT decoding helpers (reference impl — HS* only for determinism)
# ---------------------------------------------------------------------------
def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _parse_jwt(token: str) -> tuple[dict[str, object], dict[str, object], bytes, bytes]:
    """Split a compact JWT into (header, payload, signing_input, signature).

    TI-INV-05: this helper is ONLY called for JWT verification. Opaque tokens
    SHALL never reach here — the shape check below fails them fast.
    """
    if not isinstance(token, str) or token.count(".") != 2:
        raise InvalidTokenError(
            "TI-INV-05: token is not a JWT (three dot-separated segments); "
            "opaque tokens MUST be introspected remotely."
        )
    h_b, p_b, s_b = token.split(".")
    try:
        header = json.loads(_b64url_decode(h_b).decode())
        payload = json.loads(_b64url_decode(p_b).decode())
        signature = _b64url_decode(s_b)
    except Exception as exc:
        raise InvalidTokenError(
            f"TI-INV-01: malformed JWT segment — {type(exc).__name__}."
        ) from exc
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise InvalidTokenError("TI-INV-01: JWT header/payload MUST be objects.")
    signing_input = f"{h_b}.{p_b}".encode()
    return header, payload, signing_input, signature


def _hs_verify(algorithm: str, secret: bytes, signing_input: bytes, signature: bytes) -> bool:
    """Constant-time HMAC verification for HS256/HS384/HS512.

    The reference implementation covers HMAC so the invariants can be tested
    without pulling a JWT SDK. Real deployments inject an adapter that calls
    out to ``PyJWT`` / ``python-jose`` keeping the same invariants.
    """
    digest_map: dict[str, str] = {
        "HS256": "sha256",
        "HS384": "sha384",
        "HS512": "sha512",
    }
    name = digest_map.get(algorithm)
    if name is None:
        return False
    mac = hmac.new(secret, signing_input, getattr(hashlib, name)).digest()
    return hmac.compare_digest(mac, signature)


def make_hs256_jwt(
    secret: bytes,
    *,
    issuer: str,
    subject: str,
    audience: str | list[str],
    expires_at: int,
    not_before: int | None = None,
    scopes: list[str] | None = None,
    kid: str | None = None,
    algorithm: str = "HS256",
) -> str:
    """Test helper: mint a compact HS256 JWT with the catalog claims."""
    header: dict[str, object] = {"alg": algorithm, "typ": "JWT"}
    if kid is not None:
        header["kid"] = kid
    payload: dict[str, object] = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "exp": expires_at,
    }
    if not_before is not None:
        payload["nbf"] = not_before
    if scopes is not None:
        payload["scope"] = " ".join(scopes)
    h_b = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p_b = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{h_b}.{p_b}".encode()
    name_map = {"HS256": "sha256", "HS384": "sha384", "HS512": "sha512"}
    digest_name = name_map.get(algorithm)
    if digest_name is None:
        # Test helper: refuse to mint unsigned / unknown-alg tokens.
        raise TokenIntrospectorInvariantError(
            "TI-INV-01: make_hs256_jwt refuses to mint tokens with "
            f"unsupported algorithm {algorithm!r}."
        )
    sig = hmac.new(secret, signing_input, getattr(hashlib, digest_name)).digest()
    return f"{h_b}.{p_b}.{_b64url_encode(sig)}"


def make_none_alg_token(
    *,
    issuer: str,
    subject: str,
    audience: str,
    expires_at: int,
) -> str:
    """Test helper: mint a forged 'alg=none' token for TI-INV-01 tests."""
    header = {"alg": "none", "typ": "JWT"}
    payload = {"iss": issuer, "sub": subject, "aud": audience, "exp": expires_at}
    h_b = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p_b = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{h_b}.{p_b}."


# ---------------------------------------------------------------------------
# Internal cache entries
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _JwksCacheEntry:
    keys: tuple[SigningKey, ...]
    fetched_at: float


@dataclass(frozen=True)
class _IntrospectionCacheEntry:
    claims: TokenClaims
    cached_until: float  # wall-clock seconds; min(exp, cached_at + ttl)


# ---------------------------------------------------------------------------
# Reference implementation
# ---------------------------------------------------------------------------
@dataclass
class _RevocationSet:
    """Thread-safe revoked-token-id set (used by opaque introspection cache)."""

    _ids: set[str] = field(default_factory=set)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, token: str) -> None:
        with self._lock:
            self._ids.add(_hash_token(token))

    def contains(self, token: str) -> bool:
        with self._lock:
            return _hash_token(token) in self._ids


def _hash_token(token: str) -> str:
    # Store hashes rather than raw tokens so memory dumps never leak bearers.
    return hashlib.sha256(token.encode()).hexdigest()


class CachingTokenIntrospector:
    """Reference TokenIntrospector with JWKS + introspection caches.

    Responsibilities:

    - JWT path: parse header/payload, reject 'none' alg (TI-INV-01), verify
      signature with a key from the issuer JWKS cache (TI-INV-04), validate
      aud/exp/nbf (TI-INV-02 / TI-INV-03), and return ``TokenClaims``.
    - Opaque path: route to the registered RFC 7662 endpoint (TI-INV-05),
      cache the result up to ``min(exp, introspection_ttl_s)`` (TI-INV-06),
      and invalidate on explicit ``revoke(token)``.

    Concurrency: all caches are guarded by internal locks; lookups release
    the lock before calling adapters so adapter code CANNOT deadlock on the
    introspector's own lock.
    """

    def __init__(
        self,
        issuers: Mapping[str, IssuerConfig],
        jwks_fetcher: JwksFetcher,
        introspection_endpoint: IntrospectionEndpoint | None = None,
        *,
        introspection_ttl_s: int = DEFAULT_INTROSPECTION_TTL_S,
        clock: Clock | None = None,
    ) -> None:
        if not isinstance(issuers, Mapping) or not issuers:
            raise TokenIntrospectorInvariantError(
                "TI-INV-01: issuers MUST be a non-empty Mapping[str, IssuerConfig]."
            )
        for key, cfg in issuers.items():
            if not isinstance(cfg, IssuerConfig) or cfg.issuer != key:
                raise TokenIntrospectorInvariantError(
                    "TI-INV-01: issuer mapping key MUST equal IssuerConfig.issuer; "
                    f"got key={key!r} cfg.issuer={getattr(cfg, 'issuer', None)!r}."
                )
        if introspection_ttl_s <= 0:
            raise TokenIntrospectorInvariantError(
                f"TI-INV-06: introspection_ttl_s MUST be positive; got {introspection_ttl_s}."
            )
        self._issuers: dict[str, IssuerConfig] = dict(issuers)
        self._jwks_fetcher = jwks_fetcher
        self._introspection_endpoint = introspection_endpoint
        self._introspection_ttl_s = introspection_ttl_s
        self._clock: Clock = clock or time.time
        self._jwks_cache: dict[str, _JwksCacheEntry] = {}
        self._introspection_cache: dict[str, _IntrospectionCacheEntry] = {}
        self._revocations = _RevocationSet()
        self._lock = threading.Lock()

    # ----- public protocol surface ------------------------------------------
    def introspect(self, token: str, required_audience: str) -> TokenClaims:
        if not isinstance(token, str) or token == "":
            raise InvalidTokenError("TI-INV-02: token MUST be a non-empty str.")
        if not isinstance(required_audience, str) or required_audience == "":
            raise InvalidTokenError("TI-INV-02: required_audience MUST be a non-empty str.")
        if token.count(".") == 2:
            return self._introspect_jwt(token, required_audience)
        # TI-INV-05: anything that is not a three-segment JWT is opaque and
        # MUST be introspected remotely.
        return self._introspect_opaque(token, required_audience)

    # ----- revocation (operational entry point for TI-INV-06) ---------------
    def revoke(self, token: str) -> None:
        """Invalidate any cached introspection result for ``token``.

        TI-INV-06: revoked opaque tokens SHALL never surface cached claims on
        a subsequent introspect() call; the cache entry MUST be dropped
        atomically with the revoke.
        """
        if not isinstance(token, str) or token == "":
            return
        self._revocations.add(token)
        key = _hash_token(token)
        with self._lock:
            self._introspection_cache.pop(key, None)

    # ----- JWT path ----------------------------------------------------------
    def _introspect_jwt(self, token: str, required_audience: str) -> TokenClaims:
        header, payload, signing_input, signature = _parse_jwt(token)
        alg, cfg = self._enforce_alg_policy(header, payload)
        self._enforce_signature(alg, cfg, header, signing_input, signature)
        audiences = self._normalise_audience(payload.get("aud"))
        if required_audience not in audiences:
            raise InvalidTokenError(
                f"TI-INV-02: token aud {sorted(audiences)!r} does not include "
                f"required_audience {required_audience!r}."
            )
        now = self._clock()
        exp = self._enforce_time_bounds(payload, now)
        subject = payload.get("sub")
        if not isinstance(subject, str) or subject == "":
            raise InvalidTokenError("TI-INV-03: JWT payload 'sub' MUST be a non-empty str.")
        scopes = self._normalise_scopes(payload.get("scope"))
        return TokenClaims(
            subject=subject,
            scopes=scopes,
            audience=audiences,
            issuer=cfg.issuer,
            expires_at=int(exp),
        )

    def _enforce_alg_policy(
        self,
        header: Mapping[str, object],
        payload: Mapping[str, object],
    ) -> tuple[str, IssuerConfig]:
        """TI-INV-01: reject 'none', pin alg per issuer, return validated pair."""
        alg = header.get("alg")
        if not isinstance(alg, str):
            raise InvalidTokenError("TI-INV-01: JWT header 'alg' MUST be a str.")
        if alg in FORBIDDEN_ALGORITHMS:
            raise InvalidTokenError("TI-INV-01: the 'none' algorithm is FORBIDDEN; refusing token.")
        issuer = payload.get("iss")
        if not isinstance(issuer, str) or issuer == "":
            raise InvalidTokenError("TI-INV-01: JWT payload 'iss' MUST be a non-empty str.")
        cfg = self._issuers.get(issuer)
        if cfg is None:
            raise InvalidTokenError(f"TI-INV-01: unknown issuer {issuer!r}; no pinned policy.")
        if alg not in cfg.allowed_algorithms:
            raise InvalidTokenError(
                f"TI-INV-01: algorithm {alg!r} is not pinned for issuer "
                f"{issuer!r}; allowed={sorted(cfg.allowed_algorithms)!r}."
            )
        return alg, cfg

    def _enforce_signature(
        self,
        alg: str,
        cfg: IssuerConfig,
        header: Mapping[str, object],
        signing_input: bytes,
        signature: bytes,
    ) -> None:
        """TI-INV-01 + TI-INV-04: signature must verify against a cached key."""
        keys = self._resolve_jwks(cfg)
        kid = header.get("kid")
        if kid is not None and not isinstance(kid, str):
            raise InvalidTokenError("TI-INV-01: JWT header 'kid' MUST be a str when present.")
        if not self._verify_signature(alg, keys, kid, signing_input, signature):
            raise InvalidTokenError(
                "TI-INV-01: JWT signature verification FAILED against the "
                "pinned key set for this issuer."
            )

    def _enforce_time_bounds(self, payload: Mapping[str, object], now: float) -> float:
        """TI-INV-03: reject expired and not-yet-valid tokens, return exp."""
        exp = payload.get("exp")
        if not isinstance(exp, int | float):
            raise InvalidTokenError("TI-INV-03: JWT payload 'exp' MUST be numeric.")
        if now >= float(exp):
            raise InvalidTokenError("TI-INV-03: token is expired; no claim surface is returned.")
        nbf = payload.get("nbf")
        if nbf is not None:
            if not isinstance(nbf, int | float):
                raise InvalidTokenError(
                    "TI-INV-03: JWT payload 'nbf' MUST be numeric when present."
                )
            if now < float(nbf):
                raise InvalidTokenError(
                    "TI-INV-03: token is not yet valid (now < nbf); no claim surface is returned."
                )
        return float(exp)

    # ----- opaque path -------------------------------------------------------
    def _introspect_opaque(self, token: str, required_audience: str) -> TokenClaims:
        if self._introspection_endpoint is None:
            raise InvalidTokenError(
                "TI-INV-05: opaque token received but no introspection "
                "endpoint is registered; refusing local parsing."
            )
        if self._revocations.contains(token):
            raise InvalidTokenError(
                "TI-INV-06: token has been revoked; cached introspection results are invalidated."
            )
        now = self._clock()
        key = _hash_token(token)
        cached = self._lookup_introspection(key, now)
        if cached is not None:
            claims = cached
        else:
            response = self._introspection_endpoint.introspect(token)
            claims = self._claims_from_rfc7662(response)
            self._store_introspection(key, claims, now)

        if required_audience not in claims.audience:
            raise InvalidTokenError(
                "TI-INV-02: opaque-token audience "
                f"{sorted(claims.audience)!r} does not include "
                f"required_audience {required_audience!r}."
            )
        if now >= float(claims.expires_at):
            # TI-INV-06: drop the stale entry so it cannot surface again.
            with self._lock:
                self._introspection_cache.pop(key, None)
            raise InvalidTokenError(
                "TI-INV-03: opaque token is expired per the authorization server response."
            )
        return claims

    # ----- JWKS resolution ---------------------------------------------------
    def _resolve_jwks(self, cfg: IssuerConfig) -> tuple[SigningKey, ...]:
        now = self._clock()
        with self._lock:
            entry = self._jwks_cache.get(cfg.issuer)
            if entry is not None and now - entry.fetched_at < cfg.jwks_max_age_s:
                return entry.keys
        # TI-INV-04: fetch OUTSIDE the lock so adapter code cannot self-deadlock.
        fetched = self._jwks_fetcher.fetch(cfg.issuer)
        if not isinstance(fetched, list) or not fetched:
            raise InvalidTokenError(
                f"TI-INV-04: JWKS fetch returned empty key set for issuer {cfg.issuer!r}."
            )
        for k in fetched:
            if not isinstance(k, SigningKey):
                raise InvalidTokenError("TI-INV-04: JwksFetcher MUST return SigningKey instances.")
        frozen = tuple(fetched)
        with self._lock:
            self._jwks_cache[cfg.issuer] = _JwksCacheEntry(keys=frozen, fetched_at=now)
        return frozen

    def _verify_signature(
        self,
        alg: str,
        keys: tuple[SigningKey, ...],
        kid: str | None,
        signing_input: bytes,
        signature: bytes,
    ) -> bool:
        candidates = [k for k in keys if k.algorithm == alg]
        if kid is not None:
            candidates = [k for k in candidates if k.kid == kid]
        return any(_hs_verify(alg, k.secret, signing_input, signature) for k in candidates)

    # ----- RFC 7662 parsing --------------------------------------------------
    def _claims_from_rfc7662(self, response: Mapping[str, object]) -> TokenClaims:
        if not isinstance(response, Mapping):
            raise InvalidTokenError("TI-INV-05: introspection response MUST be a JSON object.")
        active = response.get(_RFC7662_ACTIVE)
        if active is not True:
            raise InvalidTokenError(
                "TI-INV-05: RFC 7662 'active=false' response means the token "
                "is NOT valid; no claims are returned."
            )
        sub = response.get("sub")
        iss = response.get("iss")
        exp = response.get("exp")
        if not isinstance(sub, str) or sub == "":
            raise InvalidTokenError("TI-INV-05: introspection response missing non-empty 'sub'.")
        if not isinstance(iss, str) or iss == "":
            raise InvalidTokenError("TI-INV-05: introspection response missing non-empty 'iss'.")
        if not isinstance(exp, int | float):
            raise InvalidTokenError("TI-INV-05: introspection response missing numeric 'exp'.")
        audience = self._normalise_audience(response.get("aud"))
        scopes = self._normalise_scopes(response.get("scope"))
        return TokenClaims(
            subject=sub,
            scopes=scopes,
            audience=audience,
            issuer=iss,
            expires_at=int(exp),
        )

    # ----- introspection cache (TI-INV-06) ----------------------------------
    def _lookup_introspection(self, key: str, now: float) -> TokenClaims | None:
        with self._lock:
            entry = self._introspection_cache.get(key)
            if entry is None:
                return None
            if now >= entry.cached_until:
                # Expired — drop so callers never see stale claims.
                self._introspection_cache.pop(key, None)
                return None
            return entry.claims

    def _store_introspection(self, key: str, claims: TokenClaims, now: float) -> None:
        # TI-INV-06: TTL MUST be min(exp, now + introspection_ttl_s).
        ttl_end = now + self._introspection_ttl_s
        cached_until = min(float(claims.expires_at), ttl_end)
        if cached_until <= now:
            # Never insert an already-stale entry.
            return
        with self._lock:
            self._introspection_cache[key] = _IntrospectionCacheEntry(
                claims=claims, cached_until=cached_until
            )

    # ----- helpers -----------------------------------------------------------
    @staticmethod
    def _normalise_audience(raw: object) -> frozenset[str]:
        if isinstance(raw, str):
            return frozenset({raw}) if raw else frozenset()
        if isinstance(raw, list):
            out: set[str] = set()
            for item in raw:
                if not isinstance(item, str) or item == "":
                    raise InvalidTokenError("TI-INV-02: aud list entries MUST be non-empty strs.")
                out.add(item)
            return frozenset(out)
        raise InvalidTokenError("TI-INV-02: aud claim MUST be a str or list[str].")

    @staticmethod
    def _normalise_scopes(raw: object) -> frozenset[str]:
        if raw is None:
            return frozenset()
        if isinstance(raw, str):
            return frozenset({s for s in raw.split() if s})
        if isinstance(raw, list):
            out: set[str] = set()
            for item in raw:
                if not isinstance(item, str):
                    raise InvalidTokenError("TI-INV-02: scope list entries MUST be strs.")
                if item:
                    out.add(item)
            return frozenset(out)
        raise InvalidTokenError("TI-INV-02: scope claim MUST be a str or list[str].")

    # ----- introspection for tests ------------------------------------------
    @property
    def jwks_cache_size(self) -> int:
        with self._lock:
            return len(self._jwks_cache)

    @property
    def introspection_cache_size(self) -> int:
        with self._lock:
            return len(self._introspection_cache)


# ---------------------------------------------------------------------------
# Reference adapters (test fixtures)
# ---------------------------------------------------------------------------
class StaticJwksFetcher:
    """In-memory JwksFetcher; also counts fetch calls so tests can assert caching."""

    def __init__(self, keys_by_issuer: Mapping[str, list[SigningKey]]) -> None:
        self._keys: dict[str, list[SigningKey]] = {k: list(v) for k, v in keys_by_issuer.items()}
        self.fetch_count: dict[str, int] = dict.fromkeys(self._keys, 0)
        self._lock = threading.Lock()

    def fetch(self, issuer: str) -> list[SigningKey]:
        with self._lock:
            self.fetch_count[issuer] = self.fetch_count.get(issuer, 0) + 1
            return list(self._keys.get(issuer, []))

    def rotate(self, issuer: str, keys: list[SigningKey]) -> None:
        with self._lock:
            self._keys[issuer] = list(keys)


class StaticIntrospectionEndpoint:
    """In-memory RFC 7662 endpoint; active/inactive controlled per token."""

    def __init__(
        self,
        responses: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        self._responses: dict[str, dict[str, object]] = {
            k: dict(v) for k, v in (responses or {}).items()
        }
        self.call_count = 0
        self._lock = threading.Lock()

    def set(self, token: str, response: Mapping[str, object]) -> None:
        with self._lock:
            self._responses[token] = dict(response)

    def set_inactive(self, token: str) -> None:
        with self._lock:
            self._responses[token] = {_RFC7662_ACTIVE: False}

    def introspect(self, token: str) -> Mapping[str, object]:
        with self._lock:
            self.call_count += 1
            entry = self._responses.get(token)
            if entry is None:
                return {_RFC7662_ACTIVE: False}
            return dict(entry)


__all__ = [
    "DEFAULT_INTROSPECTION_TTL_S",
    "DEFAULT_JWKS_MAX_AGE_S",
    "FORBIDDEN_ALGORITHMS",
    "CachingTokenIntrospector",
    "Clock",
    "IntrospectionEndpoint",
    "InvalidTokenError",
    "IssuerConfig",
    "JwksFetcher",
    "SigningKey",
    "StaticIntrospectionEndpoint",
    "StaticJwksFetcher",
    "TokenClaims",
    "TokenIntrospector",
    "TokenIntrospectorInvariantError",
    "make_hs256_jwt",
    "make_none_alg_token",
]
