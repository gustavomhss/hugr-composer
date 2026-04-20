"""Tests for the FastAPI `FeatureToggleAdapter`."""

from __future__ import annotations


def test_adapter_imports_cleanly() -> None:
    from core.venous._adapters.fastapi import FeatureToggleAdapter

    for name in ("install", "is_active", "get_registry"):
        assert hasattr(FeatureToggleAdapter, name)


def test_install_attaches_registry() -> None:
    from fastapi import FastAPI

    from core.venous._adapters.fastapi.FeatureToggleAdapter import install
    from core.venous.flags.FeatureToggle.FeatureToggle import FeatureToggleRegistry

    app = FastAPI()
    reg = install(app)
    assert isinstance(reg, FeatureToggleRegistry)
    assert app.state.toggles is reg


def test_inactive_toggle_blocks_route() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.FeatureToggleAdapter import install, is_active

    app = FastAPI()
    install(app)

    @app.get("/beta", dependencies=[Depends(is_active("beta_ui"))])
    async def _beta() -> dict:  # pragma: no cover
        return {"ok": True}

    with TestClient(app) as client:
        # Unknown key → off-by-default (FT-INV-02) → 404.
        assert client.get("/beta").status_code == 404


def test_active_toggle_admits_request() -> None:
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from core.venous._adapters.fastapi.FeatureToggleAdapter import install, is_active

    app = FastAPI()
    reg = install(app)

    class _AlwaysOn:
        key = "beta_ui"

        def is_active(self, _ctx) -> bool:
            return True

    reg.register(_AlwaysOn())

    @app.get("/beta", dependencies=[Depends(is_active("beta_ui"))])
    async def _beta() -> dict:
        return {"ok": True}

    with TestClient(app) as client:
        r = client.get("/beta")
        assert r.status_code == 200


if __name__ == "__main__":
    import sys

    tests = [
        test_adapter_imports_cleanly,
        test_install_attaches_registry,
        test_inactive_toggle_blocks_route,
        test_active_toggle_admits_request,
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
