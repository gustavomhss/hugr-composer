"""Tests for the FastAPI `RequestGuardAdapter`.

Three contracts:

1. Module imports cleanly and exposes `require`.
2. `require(...)` wires into FastAPI, returns the principal on allow.
3. Deny paths map to 401 / 403 per the primitive's `GuardOutcome`.
"""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import RequestGuardAdapter

    assert hasattr(RequestGuardAdapter, "require")
    assert callable(RequestGuardAdapter.require)


def test_allow_path_returns_principal() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.RequestGuardAdapter import require
    from core.venous.auth.CurrentPrincipal.CurrentPrincipal import authenticated
    from core.venous.auth.RequestGuard.RequestGuard import RoleGuard

    principal = authenticated(subject_id="u1", roles=frozenset({"admin"}))
    app = FastAPI()

    @app.get("/admin")
    async def _admin(p=Depends(require(RoleGuard("admin"), principal=lambda _r: principal))) -> dict:
        return {"sub": p.subject_id}

    with TestClient(app) as client:
        r = client.get("/admin")
        assert r.status_code == 200
        assert r.json() == {"sub": "u1"}


def test_deny_forbidden_maps_to_403() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.RequestGuardAdapter import require
    from core.venous.auth.CurrentPrincipal.CurrentPrincipal import authenticated
    from core.venous.auth.RequestGuard.RequestGuard import RoleGuard

    principal = authenticated(subject_id="u2", roles=frozenset({"viewer"}))
    app = FastAPI()

    @app.get("/admin", dependencies=[Depends(require(RoleGuard("admin"), principal=lambda _r: principal))])
    async def _admin() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/admin").status_code == 403


def test_deny_unauthenticated_maps_to_401() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.RequestGuardAdapter import require
    from core.venous.auth.RequestGuard.RequestGuard import RoleGuard

    app = FastAPI()

    @app.get("/admin", dependencies=[Depends(require(RoleGuard("admin")))])
    async def _admin() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/admin").status_code == 401


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_allow_path_returns_principal,
        test_deny_forbidden_maps_to_403,
        test_deny_unauthenticated_maps_to_401,
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
