"""Concurrency / linearizability harness for TokenIntrospector.

Confirms that concurrent introspection + revoke operations never surface
stale cached claims and that the JWKS cache performs at most O(1) fetches
per max-age window regardless of parallel callers.
"""

from __future__ import annotations

import threading

from TokenIntrospector import (
    CachingTokenIntrospector,
    InvalidTokenError,
    IssuerConfig,
    SigningKey,
    StaticIntrospectionEndpoint,
    StaticJwksFetcher,
    make_hs256_jwt,
)

ISSUER = "https://c.example.com"
AUD = "c-aud"
SECRET = b"concurrent-secret-key-material-32-bytes!!"


def _build(ttl_s: int = 60, jwks_max_age_s: int = 300):
    fetcher = StaticJwksFetcher({
        ISSUER: [SigningKey(kid="k", algorithm="HS256", secret=SECRET)],
    })
    endpoint = StaticIntrospectionEndpoint()
    ti = CachingTokenIntrospector(
        issuers={ISSUER: IssuerConfig(
            issuer=ISSUER, allowed_algorithms=frozenset({"HS256"}),
            jwks_max_age_s=jwks_max_age_s,
        )},
        jwks_fetcher=fetcher,
        introspection_endpoint=endpoint,
        introspection_ttl_s=ttl_s,
        clock=lambda: 1_700_000_000.0,
    )
    return ti, fetcher, endpoint


def test_concurrent_jwt_introspections_preserve_cache_bounds() -> None:
    ti, fetcher, _ = _build()
    token = make_hs256_jwt(
        SECRET, issuer=ISSUER, subject="u", audience=AUD,
        expires_at=1_700_000_500, kid="k",
    )
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            for _ in range(100):
                ti.introspect(token, AUD)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker) for _ in range(16)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    # Exactly ONE JWKS fetch: the cache ensures no thundering herd.
    assert fetcher.fetch_count[ISSUER] == 1


def test_concurrent_revoke_then_introspect_linearizable() -> None:
    ti, _, endpoint = _build(ttl_s=600)
    endpoint.set("x", {
        "active": True, "sub": "s", "iss": ISSUER, "aud": AUD, "exp": 1_700_000_500,
    })
    ti.introspect("x", AUD)  # prime cache

    leaked: list[int] = []
    lock = threading.Lock()
    start = threading.Event()

    def introspector() -> None:
        start.wait()
        for _ in range(30):
            try:
                ti.introspect("x", AUD)
            except InvalidTokenError:
                return
            else:
                # If revocation already landed but cache still served claims,
                # that is a TI-INV-06 violation.
                if "x" in _revoked_snapshot:  # type: ignore[name-defined]
                    with lock:
                        leaked.append(1)

    _revoked_snapshot: set[str] = set()

    def revoker() -> None:
        start.wait()
        ti.revoke("x")
        _revoked_snapshot.add("x")

    ts = [threading.Thread(target=introspector) for _ in range(6)]
    rt = threading.Thread(target=revoker)
    for t in ts:
        t.start()
    rt.start()
    start.set()
    rt.join()
    for t in ts:
        t.join()
    # Any introspect that observed the revoked-snapshot flag after success would
    # have leaked; the revoke atomically clears the cache so leaked stays empty.
    assert leaked == []


def test_concurrent_introspection_with_mixed_tokens() -> None:
    ti, _, endpoint = _build(ttl_s=600)
    tokens = [f"opq-{i}" for i in range(20)]
    for t in tokens:
        endpoint.set(t, {
            "active": True, "sub": t, "iss": ISSUER, "aud": AUD, "exp": 1_700_000_500,
        })

    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker(slice_start: int) -> None:
        try:
            for i in range(slice_start, slice_start + len(tokens)):
                ti.introspect(tokens[i % len(tokens)], AUD)
        except BaseException as exc:  # pragma: no cover
            with lock:
                errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errors
    assert ti.introspection_cache_size == len(tokens)
