"""Chaos / game-day tests for TokenIntrospector.

Simulates key rotation, endpoint failures, clock skew, revocation storms,
and malformed inputs to confirm the primitive never surfaces cached claims
past their TTL and never trusts unverified material.
"""

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
    make_hs256_jwt,
    make_none_alg_token,
)

ISSUER = "https://auth.example.com"
AUD = "aud-1"
SECRET = b"chaos-secret-key-material-minimum-256-bits!!"


def _build(now: float = 1_700_000_000.0, ttl_s: int = 60, jwks_max_age_s: int = 300):
    box = [now]
    clock = lambda: box[0]
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k1", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    cfg = {ISSUER: IssuerConfig(
        issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}),
        jwks_max_age_s=jwks_max_age_s,
    )}
    ti = CachingTokenIntrospector(
        issuers=cfg, jwks_fetcher=fetcher,
        introspection_endpoint=endpoint, introspection_ttl_s=ttl_s, clock=clock,
    )
    return ti, fetcher, endpoint, box


def test_chaos_endpoint_flaps_active_then_inactive() -> None:
    ti, _, endpoint, _ = _build(ttl_s=600)
    endpoint.set("t", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUD, "exp": 1_700_001_000,
    })
    ti.introspect("t", AUD)
    endpoint.set_inactive("t")
    # Cached entry still works (expected behavior for a cache); revocation is
    # the explicit signal.
    ti.introspect("t", AUD)
    ti.revoke("t")
    with pytest.raises(InvalidTokenError):
        ti.introspect("t", AUD)


def test_chaos_mass_revocation() -> None:
    ti, _, endpoint, _ = _build(ttl_s=600)
    for i in range(50):
        endpoint.set(f"t{i}", {
            "active": True, "sub": f"u{i}", "iss": ISSUER, "aud": AUD,
            "exp": 1_700_001_000,
        })
        ti.introspect(f"t{i}", AUD)
    assert ti.introspection_cache_size == 50
    for i in range(50):
        ti.revoke(f"t{i}")
    assert ti.introspection_cache_size == 0


def test_chaos_clock_jumps_forward_expires_all_cached() -> None:
    ti, _, endpoint, box = _build(ttl_s=600)
    for i in range(10):
        endpoint.set(f"t{i}", {
            "active": True, "sub": f"u{i}", "iss": ISSUER, "aud": AUD,
            "exp": 1_700_000_100,
        })
        ti.introspect(f"t{i}", AUD)
    box[0] = 1_700_001_000.0
    for i in range(10):
        with pytest.raises(InvalidTokenError):
            ti.introspect(f"t{i}", AUD)


def test_chaos_malformed_jwt_rejected() -> None:
    ti, _, _, _ = _build()
    for bad in ("", "abc", "x.y", "x.y.z", "a.b.c.d"):
        with pytest.raises(InvalidTokenError):
            ti.introspect(bad, AUD)


def test_chaos_none_alg_attempts_rejected_many_times() -> None:
    ti, _, _, _ = _build()
    forged = make_none_alg_token(
        issuer=ISSUER, subject="evil", audience=AUD, expires_at=1_700_000_500,
    )
    rejected = 0
    for _ in range(50):
        try:
            ti.introspect(forged, AUD)
        except InvalidTokenError:
            rejected += 1
    assert rejected == 50


def test_chaos_concurrent_revoke_and_introspect() -> None:
    ti, _, endpoint, _ = _build(ttl_s=600)
    endpoint.set("hot", {
        "active": True, "sub": "u", "iss": ISSUER, "aud": AUD, "exp": 1_700_001_000,
    })
    errors: list[BaseException] = []
    lock = threading.Lock()
    stop = threading.Event()

    def introspector() -> None:
        while not stop.is_set():
            try:
                ti.introspect("hot", AUD)
            except InvalidTokenError:
                pass  # post-revoke path
            except BaseException as exc:  # pragma: no cover
                with lock:
                    errors.append(exc)

    def revoker() -> None:
        for _ in range(50):
            ti.revoke("hot")

    threads = [threading.Thread(target=introspector) for _ in range(4)]
    rt = threading.Thread(target=revoker)
    for t in threads:
        t.start()
    rt.start()
    rt.join()
    stop.set()
    for t in threads:
        t.join()
    assert not errors


def test_chaos_jwks_rotation_under_load() -> None:
    ti, fetcher, _, box = _build(jwks_max_age_s=10)
    jwt = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="s", audience=AUD,
        expires_at=1_700_100_000, kid="k1",
    )
    for _ in range(5):
        ti.introspect(jwt, AUD)
    fetcher.rotate(ISSUER, [SigningKey(kid="k2", algorithm="HS256", secret=b"x" * 32)])
    box[0] += 20
    with pytest.raises(InvalidTokenError):
        ti.introspect(jwt, AUD)
