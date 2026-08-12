"""Unit tests for TokenIntrospector — three per invariant (confirms / prevents / under_failure)."""

from __future__ import annotations

import threading

import pytest
from TokenIntrospector import (
    CachingTokenIntrospector,
    InvalidTokenError,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
    TokenIntrospectorInvariantError,
    make_hs256_jwt,
    make_none_alg_token,
)

ISSUER = "https://auth.example.com"
AUDIENCE = "api.example.com"
SECRET = b"super-secret-hmac-key-minimum-length-256-bits!"


def _build(
    *,
    ttl_s: int = 60,
    jwks_max_age_s: int = 300,
    now: float = 1_700_000_000.0,
) -> tuple[CachingTokenIntrospector, StaticJwksFetcher, StaticIntrospectionEndpoint, list[float]]:
    clock_box = [now]

    def clock() -> float:
        return clock_box[0]

    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k1", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    cfg = {ISSUER: IssuerConfig(
        issuer=ISSUER,
        allowed_algorithms=frozenset({"HS256"}),
        jwks_max_age_s=jwks_max_age_s,
    )}
    introspector = CachingTokenIntrospector(
        issuers=cfg,
        jwks_fetcher=fetcher,
        introspection_endpoint=endpoint,
        introspection_ttl_s=ttl_s,
        clock=clock,
    )
    return introspector, fetcher, endpoint, clock_box


def _valid_jwt(
    *,
    expires_at: int = 1_700_000_600,
    audience: str | list[str] = AUDIENCE,
    subject: str = "user-1",
    scopes: list[str] | None = None,
    not_before: int | None = None,
    kid: str | None = "k1",
    algorithm: str = "HS256",
    secret: bytes = SECRET,
) -> str:
    return make_hs256_jwt(
        secret,
        issuer=ISSUER,
        subject=subject,
        audience=audience,
        expires_at=expires_at,
        not_before=not_before,
        scopes=scopes,
        kid=kid,
        algorithm=algorithm,
    )


# ---------------------------------------------------------------------------
# TI_INV_01 — pinned algorithm / reject 'none'
# ---------------------------------------------------------------------------
def test_inv_pinned_algorithm_confirms() -> None:
    ti, _, _, _ = _build()
    claims = ti.introspect(_valid_jwt(), AUDIENCE)
    assert claims.subject == "user-1"
    assert claims.issuer == ISSUER


def test_inv_pinned_algorithm_prevents() -> None:
    ti, _, _, _ = _build()
    forged = make_none_alg_token(
        issuer=ISSUER, subject="evil", audience=AUDIENCE, expires_at=1_700_000_600,
    )
    with pytest.raises(InvalidTokenError, match="TI-INV-01"):
        ti.introspect(forged, AUDIENCE)

    # Cannot register 'none' in the issuer policy either.
    with pytest.raises(TokenIntrospectorInvariantError, match="TI-INV-01"):
        IssuerConfig(
            issuer=ISSUER, allowed_algorithms=frozenset({"none"}),
        )


def test_inv_pinned_algorithm_under_failure() -> None:
    # An issuer that pins HS256 MUST reject HS512 even though it is a valid JWS alg.
    ti, _, _, _ = _build()
    hs512_token = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="x", audience=AUDIENCE,
        expires_at=1_700_000_600, kid="k1", algorithm="HS512",
    )
    with pytest.raises(InvalidTokenError, match="TI-INV-01"):
        ti.introspect(hs512_token, AUDIENCE)


# ---------------------------------------------------------------------------
# TI_INV_02 — audience enforcement
# ---------------------------------------------------------------------------
def test_inv_audience_enforcement_confirms() -> None:
    ti, _, _, _ = _build()
    # Multi-audience list including the required audience MUST pass.
    token = _valid_jwt(audience=["other.example.com", AUDIENCE])
    claims = ti.introspect(token, AUDIENCE)
    assert AUDIENCE in claims.audience


def test_inv_audience_enforcement_prevents() -> None:
    ti, _, _, _ = _build()
    token = _valid_jwt(audience="different.example.com")
    with pytest.raises(InvalidTokenError, match="TI-INV-02"):
        ti.introspect(token, AUDIENCE)


def test_inv_audience_enforcement_under_failure() -> None:
    ti, _, _, _ = _build()
    # A list of ONLY wrong audiences; repeated attempts all reject.
    token = _valid_jwt(audience=["a", "b", "c"])
    for _ in range(5):
        with pytest.raises(InvalidTokenError, match="TI-INV-02"):
            ti.introspect(token, AUDIENCE)


# ---------------------------------------------------------------------------
# TI_INV_03 — time-bounds (exp / nbf)
# ---------------------------------------------------------------------------
def test_inv_time_bounds_confirms() -> None:
    ti, _, _, clock_box = _build(now=1_700_000_000.0)
    token = _valid_jwt(expires_at=1_700_000_300, not_before=1_699_999_900)
    claims = ti.introspect(token, AUDIENCE)
    assert claims.expires_at == 1_700_000_300


def test_inv_time_bounds_prevents() -> None:
    ti, _, _, clock_box = _build(now=1_700_000_000.0)
    expired = _valid_jwt(expires_at=1_699_000_000)
    with pytest.raises(InvalidTokenError, match="TI-INV-03"):
        ti.introspect(expired, AUDIENCE)

    future = _valid_jwt(expires_at=1_700_500_000, not_before=1_700_100_000)
    with pytest.raises(InvalidTokenError, match="TI-INV-03"):
        ti.introspect(future, AUDIENCE)


def test_inv_time_bounds_under_failure() -> None:
    # As the clock walks past exp the token MUST transition from valid to invalid.
    ti, _, _, clock_box = _build(now=1_700_000_000.0)
    token = _valid_jwt(expires_at=1_700_000_100)
    ti.introspect(token, AUDIENCE)  # fine
    clock_box[0] = 1_700_000_200.0  # past exp
    with pytest.raises(InvalidTokenError, match="TI-INV-03"):
        ti.introspect(token, AUDIENCE)


# ---------------------------------------------------------------------------
# TI_INV_04 — JWKS bounded caching
# ---------------------------------------------------------------------------
def test_inv_jwks_cache_confirms() -> None:
    ti, fetcher, _, _ = _build(jwks_max_age_s=300)
    for _ in range(5):
        ti.introspect(_valid_jwt(), AUDIENCE)
    # Only ONE JWKS fetch because the cache is warm and within max-age.
    assert fetcher.fetch_count[ISSUER] == 1


def test_inv_jwks_cache_prevents() -> None:
    # After max-age elapses the cache entry MUST be refetched, so a ROTATED
    # key at the issuer takes effect instead of being trusted stale forever.
    ti, fetcher, _, clock_box = _build(jwks_max_age_s=60)
    ti.introspect(_valid_jwt(), AUDIENCE)
    assert fetcher.fetch_count[ISSUER] == 1

    new_secret = b"rotated-secret-key-material-different!!!"
    fetcher.rotate(ISSUER, [SigningKey(kid="k2", algorithm="HS256", secret=new_secret)])

    clock_box[0] += 120.0  # advance past jwks_max_age_s
    # Old key-id signed token now fails: the rotated JWKS no longer contains k1.
    with pytest.raises(InvalidTokenError, match="TI-INV-01"):
        ti.introspect(_valid_jwt(kid="k1"), AUDIENCE)
    # Refetch happened.
    assert fetcher.fetch_count[ISSUER] == 2


def test_inv_jwks_cache_under_failure() -> None:
    # An empty JWKS fetch MUST raise — stale/no keys cannot be trusted.
    issuer = "https://bad.example.com"
    cfg = {issuer: IssuerConfig(issuer=issuer, allowed_algorithms=frozenset({"HS256"}))}
    fetcher = StaticJwksFetcher({issuer: []})
    ti = CachingTokenIntrospector(issuers=cfg, jwks_fetcher=fetcher)
    token = make_hs256_jwt(
        SECRET, issuer=issuer, subject="u", audience=AUDIENCE,
        expires_at=9_999_999_999, kid="k1",
    )
    with pytest.raises(InvalidTokenError, match="TI-INV-04"):
        ti.introspect(token, AUDIENCE)


# ---------------------------------------------------------------------------
# TI_INV_05 — opaque tokens via RFC 7662
# ---------------------------------------------------------------------------
def test_inv_opaque_rfc7662_confirms() -> None:
    ti, _, endpoint, _ = _build()
    endpoint.set("opaque-123", {
        "active": True, "sub": "user-2", "iss": ISSUER,
        "aud": AUDIENCE, "exp": 1_700_000_500, "scope": "read write",
    })
    claims = ti.introspect("opaque-123", AUDIENCE)
    assert claims.subject == "user-2"
    assert claims.scopes == frozenset({"read", "write"})
    assert endpoint.call_count == 1


def test_inv_opaque_rfc7662_prevents() -> None:
    # An opaque token with NO introspection endpoint MUST be refused —
    # the primitive SHALL NEVER parse opaque tokens locally.
    cfg = {ISSUER: IssuerConfig(issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}))}
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k1", algorithm="HS256", secret=SECRET)],
    })
    ti = CachingTokenIntrospector(issuers=cfg, jwks_fetcher=fetcher)
    with pytest.raises(InvalidTokenError, match="TI-INV-05"):
        ti.introspect("just-an-opaque-string", AUDIENCE)


def test_inv_opaque_rfc7662_under_failure() -> None:
    # active=false MUST yield no claims — the introspector refuses.
    ti, _, endpoint, _ = _build()
    endpoint.set("bad-token", {"active": False})
    with pytest.raises(InvalidTokenError, match="TI-INV-05"):
        ti.introspect("bad-token", AUDIENCE)

    # Unknown token defaults to active=false → refused.
    with pytest.raises(InvalidTokenError, match="TI-INV-05"):
        ti.introspect("unseen-token", AUDIENCE)


# ---------------------------------------------------------------------------
# TI_INV_06 — cache TTL, revocation
# ---------------------------------------------------------------------------
def test_inv_cache_ttl_confirms() -> None:
    ti, _, endpoint, _ = _build(ttl_s=120)
    endpoint.set("t1", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUDIENCE,
        "exp": 1_700_000_060,  # exp in 60s from clock=1_700_000_000
    })
    ti.introspect("t1", AUDIENCE)
    ti.introspect("t1", AUDIENCE)
    ti.introspect("t1", AUDIENCE)
    # Exactly one remote call; subsequent hits served from cache bounded by exp (60s < ttl 120s).
    assert endpoint.call_count == 1


def test_inv_cache_ttl_prevents() -> None:
    # After revoke(), the cached entry MUST be purged and subsequent calls
    # MUST refuse the token.
    ti, _, endpoint, _ = _build(ttl_s=600)
    endpoint.set("t2", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUDIENCE,
        "exp": 1_700_000_500,
    })
    ti.introspect("t2", AUDIENCE)
    assert ti.introspection_cache_size == 1

    ti.revoke("t2")
    assert ti.introspection_cache_size == 0
    with pytest.raises(InvalidTokenError, match="TI-INV-06"):
        ti.introspect("t2", AUDIENCE)


def test_inv_cache_ttl_under_failure() -> None:
    # Clock advances past exp → cached entry MUST NOT surface; new call
    # observes expiry and raises.
    ti, _, endpoint, clock_box = _build(ttl_s=3600)
    endpoint.set("t3", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUDIENCE,
        "exp": 1_700_000_050,
    })
    ti.introspect("t3", AUDIENCE)
    clock_box[0] = 1_700_000_100.0
    with pytest.raises(InvalidTokenError, match="TI-INV-03"):
        ti.introspect("t3", AUDIENCE)
    # Cache entry is purged.
    assert ti.introspection_cache_size == 0


# ---------------------------------------------------------------------------
# Thread-safety smoke test (used by several under_failure invariants)
# ---------------------------------------------------------------------------
def test_concurrent_jwt_introspection_is_safe() -> None:
    ti, fetcher, _, _ = _build()
    token = _valid_jwt()
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(20):
                ti.introspect(token, AUDIENCE)
        except BaseException as exc:  # pragma: no cover — defensive
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # The JWKS fetch is bounded by the cache; typically exactly one.
    assert fetcher.fetch_count[ISSUER] >= 1
