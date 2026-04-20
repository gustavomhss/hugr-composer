"""Tests for the FastAPI `AuditLogAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import AuditLogAdapter

    assert callable(AuditLogAdapter.install)


def test_install_attaches_log_and_router() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    log = install(app, hmac_secret=b"s3cretXXXXXXXXXXXXXXXXXXXXXXXXXX")
    assert app.state.audit_log is log
    paths = [r.path for r in app.router.routes]
    assert any("/audit-logs" in p for p in paths)


def test_append_verify_roundtrip() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.AuditLogAdapter import install

    app = FastAPI()
    install(app, hmac_secret=b"s3cretXXXXXXXXXXXXXXXXXXXXXXXXXX")
    client = TestClient(app)

    r = client.post("/audit-logs/?actor=alice&action=CREATE&resource=/x&outcome=success", json={"k": "v"})
    assert r.status_code == 200, r.text
    assert "entry_hash" in r.json()

    r2 = client.post("/audit-logs/verify")
    assert r2.status_code == 200
    assert r2.json()["valid"] is True


if __name__ == "__main__":
    import sys
    tests = [test_adapter_imports_cleanly, test_install_attaches_log_and_router, test_append_verify_roundtrip]
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); failed += 1
    sys.exit(1 if failed else 0)
