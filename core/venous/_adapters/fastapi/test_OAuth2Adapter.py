"""Tests for the FastAPI `OAuth2Adapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import OAuth2Adapter

    for name in ("install", "current_claims", "bearer_scheme"):
        assert hasattr(OAuth2Adapter, name)


def test_install_attaches_both_primitives() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.OAuth2Adapter import install
    from core.venous.auth.SessionStore.SessionStore import InMemorySessionStore
    from core.venous.auth.TokenIntrospector.TokenIntrospector import (
        CachingTokenIntrospector,
        IssuerConfig,
        StaticJwksFetcher,
    )

    issuers = {"https://idp": IssuerConfig(issuer="https://idp", allowed_algorithms=frozenset({"HS256"}))}
    introspector = CachingTokenIntrospector(issuers, StaticJwksFetcher({"https://idp": []}))
    session_store = InMemorySessionStore()
    app = FastAPI()
    install(app, introspector=introspector, session_store=session_store)
    assert app.state.token_introspector is introspector
    assert app.state.session_store is session_store


def test_missing_token_returns_401() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.OAuth2Adapter import current_claims, install
    from core.venous.auth.SessionStore.SessionStore import InMemorySessionStore
    from core.venous.auth.TokenIntrospector.TokenIntrospector import (
        CachingTokenIntrospector,
        IssuerConfig,
        StaticJwksFetcher,
    )

    issuers = {"https://idp": IssuerConfig(issuer="https://idp", allowed_algorithms=frozenset({"HS256"}))}
    introspector = CachingTokenIntrospector(issuers, StaticJwksFetcher({"https://idp": []}))
    app = FastAPI()
    install(app, introspector=introspector, session_store=InMemorySessionStore())

    @app.get("/me", dependencies=[Depends(current_claims("api"))])
    async def _me() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/me")
        assert r.status_code == 401


def test_valid_jwt_returns_claims() -> None:
    import time

    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.OAuth2Adapter import current_claims, install
    from core.venous.auth.SessionStore.SessionStore import InMemorySessionStore
    from core.venous.auth.TokenIntrospector.TokenIntrospector import (
        CachingTokenIntrospector,
        IssuerConfig,
        StaticJwksFetcher,
        make_hs256_jwt,
    )

    secret = b"k" * 32
    issuers = {
        "https://idp": IssuerConfig(
            issuer="https://idp",
            allowed_algorithms=frozenset({"HS256"}),
        )
    }
    from core.venous.auth.TokenIntrospector.TokenIntrospector import SigningKey

    keys = [SigningKey(kid="kid1", algorithm="HS256", secret=secret)]
    introspector = CachingTokenIntrospector(issuers, StaticJwksFetcher({"https://idp": keys}))
    now = int(time.time())
    token = make_hs256_jwt(
        secret=secret,
        issuer="https://idp",
        subject="u1",
        audience="api",
        expires_at=now + 300,
        kid="kid1",
    )
    app = FastAPI()
    install(app, introspector=introspector, session_store=InMemorySessionStore())

    @app.get("/me")
    async def _me(claims=Depends(current_claims("api"))) -> dict:
        return {"sub": claims.subject}

    with TestClient(app) as client:
        r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json() == {"sub": "u1"}


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_both_primitives,
        test_missing_token_returns_401,
        test_valid_jwt_returns_claims,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    sys.exit(1 if failed else 0)
