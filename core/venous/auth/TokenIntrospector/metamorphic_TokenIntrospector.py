"""Metamorphic + differential tests for TokenIntrospector.

Algebraic properties:
- introspect(token, aud) is deterministic for a fixed clock and JWKS cache.
- Revoke(t) is idempotent — calling revoke twice is equivalent to calling once.
- A longer aud list containing the required aud is equivalent to the required aud alone.
- Cache hit-rate monotonicity: repeated introspection of the same opaque token
  causes at most one remote call per cache lifetime.
- Differential: JWT path and opaque path surface equivalent TokenClaims when the
  authorization server returns the same subject/issuer/aud/exp.
"""

from __future__ import annotations

from TokenIntrospector import (
    CachingTokenIntrospector,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
    make_hs256_jwt,
)

ISSUER = "https://iss.example.com"
AUD = "svc"
SECRET = b"metamorphic-secret-key-material-min-length!!"


def _build(now: float = 1_700_000_000.0, ttl_s: int = 60):
    box = [now]
    clock = lambda: box[0]
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    cfg = {ISSUER: IssuerConfig(issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}))}
    ti = CachingTokenIntrospector(
        issuers=cfg, jwks_fetcher=fetcher,
        introspection_endpoint=endpoint, introspection_ttl_s=ttl_s, clock=clock,
    )
    return ti, fetcher, endpoint, box


def _jwt(**kw: object) -> str:
    return make_hs256_jwt(
        SECRET,
        issuer=str(kw.get("issuer", ISSUER)),
        subject=str(kw.get("subject", "u")),
        audience=kw.get("audience", AUD),  # type: ignore[arg-type]
        expires_at=int(kw.get("expires_at", 1_700_000_500)),
        scopes=kw.get("scopes"),  # type: ignore[arg-type]
        kid=str(kw.get("kid", "k")),
    )


def test_metamorphic_determinism_same_input_same_output() -> None:
    ti, _, _, _ = _build()
    token = _jwt(subject="ana")
    a = ti.introspect(token, AUD)
    b = ti.introspect(token, AUD)
    assert a == b


def test_metamorphic_revoke_is_idempotent() -> None:
    ti, _, endpoint, _ = _build(ttl_s=600)
    endpoint.set("tok", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUD, "exp": 1_700_001_000,
    })
    ti.introspect("tok", AUD)
    ti.revoke("tok")
    ti.revoke("tok")  # second revoke MUST be a no-op
    assert ti.introspection_cache_size == 0


def test_metamorphic_audience_set_containment_equivalence() -> None:
    ti, _, _, _ = _build()
    required_only = ti.introspect(_jwt(audience=AUD), AUD)
    with_extras = ti.introspect(_jwt(audience=[AUD, "other1", "other2"]), AUD)
    # The required_audience acceptance outcome is identical; surface contains required.
    assert AUD in required_only.audience
    assert AUD in with_extras.audience
    assert required_only.subject == with_extras.subject


def test_metamorphic_cache_monotonicity_opaque() -> None:
    ti, _, endpoint, _ = _build(ttl_s=600)
    endpoint.set("x", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUD, "exp": 1_700_001_000,
    })
    for _ in range(25):
        ti.introspect("x", AUD)
    assert endpoint.call_count == 1  # exactly one remote call


def test_differential_jwt_vs_opaque_same_claims() -> None:
    # JWT path and opaque path MUST produce structurally-equivalent TokenClaims
    # when the same subject/issuer/aud/exp/scope are presented.
    ti, _, endpoint, _ = _build()
    jwt = _jwt(subject="shared", audience=AUD, expires_at=1_700_000_400, scopes=["r", "w"])
    endpoint.set("opq", {
        "active": True, "sub": "shared", "iss": ISSUER, "aud": AUD,
        "exp": 1_700_000_400, "scope": "r w",
    })
    via_jwt = ti.introspect(jwt, AUD)
    via_opaque = ti.introspect("opq", AUD)
    assert via_jwt.subject == via_opaque.subject
    assert via_jwt.issuer == via_opaque.issuer
    assert via_jwt.audience == via_opaque.audience
    assert via_jwt.scopes == via_opaque.scopes
    assert via_jwt.expires_at == via_opaque.expires_at
