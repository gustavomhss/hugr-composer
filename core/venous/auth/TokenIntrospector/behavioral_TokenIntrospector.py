"""Behavioral end-to-end scenarios for TokenIntrospector — proves invariants at runtime."""

from __future__ import annotations

import pytest

from TokenIntrospector import (
    CachingTokenIntrospector,
    InvalidTokenError,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
    make_hs256_jwt,
    make_none_alg_token,
)

ISSUER = "https://id.example.com"
AUD = "billing-api"
SECRET = b"sixteen-bytes-secret-min-hmac-key-material!"


def _fixtures(now: float = 1_700_000_000.0, ttl_s: int = 60, jwks_max_age_s: int = 300):
    box = [now]
    clock = lambda: box[0]
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="key-1", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    cfg = {ISSUER: IssuerConfig(
        issuer=ISSUER,
        allowed_algorithms=frozenset({"HS256"}),
        jwks_max_age_s=jwks_max_age_s,
    )}
    ti = CachingTokenIntrospector(
        issuers=cfg,
        jwks_fetcher=fetcher,
        introspection_endpoint=endpoint,
        introspection_ttl_s=ttl_s,
        clock=clock,
    )
    return ti, fetcher, endpoint, box


def test_scenario_jwt_happy_path_returns_claims() -> None:
    ti, _, _, _ = _fixtures()
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="alice", audience=AUD,
        expires_at=1_700_000_600, scopes=["invoices:read"], kid="key-1",
    )
    claims = ti.introspect(jwt, AUD)
    assert claims.subject == "alice"
    assert claims.issuer == ISSUER
    assert claims.audience == frozenset({AUD})
    assert claims.scopes == frozenset({"invoices:read"})


def test_scenario_forged_none_alg_is_rejected() -> None:
    ti, _, _, _ = _fixtures()
    bad = make_none_alg_token(
        issuer=ISSUER, subject="evil", audience=AUD, expires_at=1_700_000_600,
    )
    with pytest.raises(InvalidTokenError):
        ti.introspect(bad, AUD)


def test_scenario_rotate_key_invalidates_old_tokens() -> None:
    ti, fetcher, _, box = _fixtures(jwks_max_age_s=30)
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="bob", audience=AUD,
        expires_at=1_700_100_000, kid="key-1",
    )
    assert ti.introspect(jwt, AUD).subject == "bob"

    # Rotate keys and advance time past max-age.
    fetcher.rotate(ISSUER, [SigningKey(kid="key-2", algorithm="HS256", secret=b"different!")])
    box[0] += 60
    with pytest.raises(InvalidTokenError):
        ti.introspect(jwt, AUD)


def test_scenario_opaque_token_round_trip() -> None:
    ti, _, endpoint, _ = _fixtures()
    endpoint.set("tok-42", {
        "active": True, "sub": "carol", "iss": ISSUER,
        "aud": [AUD, "other"], "exp": 1_700_000_500,
        "scope": "jobs:write",
    })
    claims = ti.introspect("tok-42", AUD)
    assert claims.subject == "carol"
    assert claims.scopes == frozenset({"jobs:write"})


def test_scenario_revoke_invalidates_cached_opaque() -> None:
    ti, _, endpoint, _ = _fixtures(ttl_s=600)
    endpoint.set("long-lived", {
        "active": True, "sub": "dan", "iss": ISSUER,
        "aud": AUD, "exp": 1_700_010_000,
    })
    assert ti.introspect("long-lived", AUD).subject == "dan"
    ti.revoke("long-lived")
    with pytest.raises(InvalidTokenError):
        ti.introspect("long-lived", AUD)


def test_scenario_audience_list_with_required_passes() -> None:
    ti, _, _, _ = _fixtures()
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="s", audience=["x", AUD, "y"],
        expires_at=1_700_000_600, kid="key-1",
    )
    assert ti.introspect(jwt, AUD).subject == "s"


def test_scenario_not_before_in_future_rejects() -> None:
    ti, _, _, _ = _fixtures(now=1_700_000_000.0)
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="early",
        audience=AUD, expires_at=1_700_100_000, not_before=1_700_050_000, kid="key-1",
    )
    with pytest.raises(InvalidTokenError):
        ti.introspect(jwt, AUD)
