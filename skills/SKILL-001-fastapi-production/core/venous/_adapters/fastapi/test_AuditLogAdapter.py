"""Tests for the FastAPI `AuditLogAdapter` (auth-gated, server-side actor)."""

from __future__ import annotations

from types import SimpleNamespace


def _fake_auth() -> object:
    """Stand-in auth dependency returning a superuser principal."""
    return SimpleNamespace(email="admin@example.com", id="u-1")


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import AuditLogAdapter

    assert callable(AuditLogAdapter.install)


def test_install_attaches_log_and_router() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    log = install(app, hmac_secret=b"s3cretXXXXXXXXXXXXXXXXXXXXXXXXXX", auth_dependency=_fake_auth)
    assert app.state.audit_log is log
    paths = [r.path for r in app.router.routes]
    assert any("/audit-logs" in p for p in paths)


def test_append_records_server_side_actor() -> None:
    """R5-S1-F2: the recorded actor comes from the principal, not the request."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    install(app, hmac_secret=b"s3cretXXXXXXXXXXXXXXXXXXXXXXXXXX", auth_dependency=_fake_auth)
    client = TestClient(app)

    # No actor in the request — and a forged one must be ignored even if sent.
    r = client.post(
        "/audit-logs/?actor=mallory&action=CREATE&resource=/x&outcome=success",
        json={"k": "v"},
    )
    assert r.status_code == 200, r.text
    assert "entry_hash" in r.json()

    r2 = client.post("/audit-logs/verify")
    assert r2.status_code == 200
    assert r2.json()["valid"] is True

    export = client.get("/audit-logs/export?since_seq=1")
    assert export.status_code == 200
    body = export.text
    assert "admin@example.com" in body, "actor must be the authenticated principal"
    assert "mallory" not in body, "client-supplied actor must be ignored (R5-S1-F2)"


def test_routes_require_auth() -> None:
    """R5-S1-F1: a failing auth dependency blocks every route."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.AuditLogAdapter import install

    def _deny() -> object:
        raise HTTPException(status_code=401, detail="unauthenticated")

    app = FastAPI()
    install(app, hmac_secret=b"s3cretXXXXXXXXXXXXXXXXXXXXXXXXXX", auth_dependency=_deny)
    client = TestClient(app)

    assert client.post("/audit-logs/?action=A&resource=/x&outcome=success").status_code == 401
    assert client.post("/audit-logs/verify").status_code == 401
    assert client.get("/audit-logs/export").status_code == 401


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_log_and_router,
        test_append_records_server_side_actor,
        test_routes_require_auth,
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
