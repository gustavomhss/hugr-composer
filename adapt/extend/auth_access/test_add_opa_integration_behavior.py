"""Behavior test for TOOL-072 add_opa_integration.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub

Then fires real HTTP requests via ASGI transport to verify the OPA
endpoints behave correctly end-to-end (with OPA sidecar mocked via
dependency override so no real OPA is needed in CI).

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_opa_integration_behavior.py -v

or::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_opa_integration_behavior.py
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Set env vars BEFORE importing the app (avoids Settings validation errors)
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-key-opa-integration!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")

import asyncio

import pytest

# ---------------------------------------------------------------------------
# Shared fixture setup (module-level so we build the project once)
# ---------------------------------------------------------------------------

_TMPDIR: tempfile.TemporaryDirectory | None = None
_PROJECT_DIR: Path | None = None


def _build_project() -> Path:
    """Generate fixture project and apply the tool once.

    Returns:
        Path to the generated project root.
    """
    global _TMPDIR, _PROJECT_DIR
    if _PROJECT_DIR is not None:
        return _PROJECT_DIR

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_opa_integration import add_opa_integration
    from tests.common.fixture_factory import create_fixture_project

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="opa_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_opa_integration(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_opa_integration failed: {result.error}")

    _PROJECT_DIR = project_dir
    return project_dir


def _load_app(project_dir: Path):
    """Load the FastAPI app from a generated project, clearing module cache.

    Args:
        project_dir: Path to the project root.

    Returns:
        FastAPI application instance.
    """
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    importlib.import_module("app.models")
    return importlib.import_module("app.main").app


async def _make_sqlite_client(project_dir: Path):
    """Create an ASGI test client backed by SQLite in-memory.

    Args:
        project_dir: Path to the project root.

    Returns:
        Tuple of (AsyncClient, AsyncSession, AsyncEngine, app).
    """
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    app = _load_app(project_dir)
    get_session_mod = importlib.import_module("app.core.session")
    base_mod = importlib.import_module("app.models.base")

    engine = create_async_engine("sqlite+aiosqlite://", echo=False, future=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(base_mod.Base.metadata.create_all)

    session = factory()

    async def _override():
        yield session

    app.dependency_overrides[get_session_mod.get_session] = _override

    # B0.11 close-out: /authz/opa/check and /authz/opa/health are now
    # gated on ``get_current_superuser`` (policy oracle + sidecar
    # reachability fingerprint). Override the dep so behavior tests can
    # still assert the 200 happy path without provisioning a real JWT.
    import uuid as _uuid

    deps_mod = importlib.import_module("app.api.deps")
    user_mod = importlib.import_module("app.models.user")
    _fake_super = user_mod.User()
    _fake_super.id = _uuid.uuid4()
    _fake_super.email = "opa_behavior@test"
    _fake_super.is_active = True
    _fake_super.is_superuser = True

    async def _fake_superuser():
        return _fake_super

    app.dependency_overrides[deps_mod.get_current_superuser] = _fake_superuser

    # Disable idempotency middleware if present (requires Redis)
    try:
        idempotency_mod = importlib.import_module("app.middleware.idempotency")
        from starlette.middleware.base import BaseHTTPMiddleware

        class _PassThrough(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                return await call_next(request)

        if hasattr(idempotency_mod, "IdempotencyMiddleware"):
            idempotency_mod.IdempotencyMiddleware = _PassThrough
    except (ModuleNotFoundError, AttributeError):
        pass

    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return client, session, engine, app


async def _teardown(app, client, session, engine) -> None:
    """Clean up client, session, engine and dependency overrides.

    Args:
        app: FastAPI application.
        client: httpx AsyncClient.
        session: SQLAlchemy AsyncSession.
        engine: SQLAlchemy AsyncEngine.
    """
    await client.aclose()
    await session.close()
    from app.models.base import Base  # type: ignore[import]
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    app.dependency_overrides.clear()


def _mock_opa_client(allow: bool = True, reason: str | None = None):
    """Create a mock OPAClient that returns a fixed decision.

    Args:
        allow: Decision to return.
        reason: Optional reason string.

    Returns:
        Mock OPAClient instance.
    """
    from app.authz.opa_models import OPADecision  # type: ignore[import]

    client = MagicMock()
    decision = OPADecision(allow=allow, reason=reason, policy_path="authz/allow")
    client.query = AsyncMock(return_value=decision)
    client.health = AsyncMock(return_value=allow)
    client.fail_open = False
    return client


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_beh_01_app_boots() -> None:
    """BEH-01: App boots cleanly after OPA integration applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_check_endpoint_allow() -> None:
    """BEH-02: POST /authz/opa/check with mocked allow=True returns allow=true."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        mock = _mock_opa_client(allow=True)
        app.dependency_overrides[opa_client_mod.get_opa_client] = lambda: mock

        payload = {
            "subject": "user@example.com",
            "action": "GET",
            "resource": "/api/v1/items",
            "context": {},
        }
        r = await client.post("/api/v1/authz/opa/check", json=payload)
        assert r.status_code == 200, f"check endpoint: {r.status_code} {r.text}"
        body = r.json()
        assert body["allow"] is True
        assert "policy_path" in body
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_check_endpoint_deny() -> None:
    """BEH-03: POST /authz/opa/check with mocked allow=False returns allow=false."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        mock = _mock_opa_client(allow=False, reason="insufficient_scope")
        app.dependency_overrides[opa_client_mod.get_opa_client] = lambda: mock

        payload = {
            "subject": "guest@example.com",
            "action": "DELETE",
            "resource": "/api/v1/admin",
            "context": {},
        }
        r = await client.post("/api/v1/authz/opa/check", json=payload)
        assert r.status_code == 200, f"check endpoint: {r.status_code} {r.text}"
        body = r.json()
        assert body["allow"] is False
        assert body["reason"] == "insufficient_scope"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_health_ok() -> None:
    """BEH-04: GET /authz/opa/health with healthy mock returns status=ok."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        mock = _mock_opa_client(allow=True)
        app.dependency_overrides[opa_client_mod.get_opa_client] = lambda: mock

        r = await client.get("/api/v1/authz/opa/health")
        assert r.status_code == 200, f"health: {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "ok"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_health_unavailable() -> None:
    """BEH-05: GET /authz/opa/health with unhealthy mock returns status=unavailable."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        mock = _mock_opa_client(allow=False)
        mock.health = AsyncMock(return_value=False)
        app.dependency_overrides[opa_client_mod.get_opa_client] = lambda: mock

        r = await client.get("/api/v1/authz/opa/health")
        assert r.status_code == 200, f"health: {r.status_code} {r.text}"
        body = r.json()
        assert body["status"] == "unavailable"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_opa_models_importable() -> None:
    """BEH-06: app.authz.opa_models imports without crash and models are valid Pydantic."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_models = importlib.import_module("app.authz.opa_models")
        # OPAInput instantiation
        inp = opa_models.OPAInput(
            subject="user@example.com",
            action="GET",
            resource="/api/v1/items",
        )
        assert inp.subject == "user@example.com"
        assert inp.context == {}

        # OPADecision instantiation
        dec = opa_models.OPADecision(
            allow=True,
            reason="allow_all",
            policy_path="authz/allow",
        )
        assert dec.allow is True
        assert dec.policy_path == "authz/allow"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_07_opa_client_importable() -> None:
    """BEH-07: app.authz.opa_client imports cleanly and OPAClient is instantiable."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        opa = opa_client_mod.OPAClient(
            opa_url="http://localhost:8181",
            policy_path="authz/allow",
            timeout_ms=200,
            fail_open=True,
        )
        assert opa.opa_url == "http://localhost:8181"
        assert opa.fail_open is True
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_08_circuit_breaker_open_returns_decision() -> None:
    """BEH-08: OPAClient with open circuit returns fail_open decision without calling OPA."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        opa_models_mod = importlib.import_module("app.authz.opa_models")

        opa = opa_client_mod.OPAClient(
            opa_url="http://localhost:9999",
            timeout_ms=10,
            fail_open=True,
        )
        # Force circuit open by recording failures past threshold
        for _ in range(5):
            opa._cb.record_failure()

        assert opa._cb.is_open()

        inp = opa_models_mod.OPAInput(
            subject="user",
            action="GET",
            resource="/foo",
        )
        decision = await opa.query(inp)
        # fail_open=True → allow=True even with circuit open
        assert decision.allow is True
        assert decision.reason == "circuit_open"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_09_opa_authz_init_exports() -> None:
    """BEH-09: app.authz.__init__ exports OPAClient, OPADecision, OPAInput, OPAMiddleware."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        authz_mod = importlib.import_module("app.authz")
        assert hasattr(authz_mod, "OPAClient")
        assert hasattr(authz_mod, "OPADecision")
        assert hasattr(authz_mod, "OPAInput")
        assert hasattr(authz_mod, "OPAMiddleware")
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_10_openapi_has_opa_paths() -> None:
    """BEH-10: OpenAPI schema includes /authz/opa paths."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        opa_paths = [p for p in paths if "opa" in p]
        assert len(opa_paths) >= 1, f"No OPA paths in OpenAPI: {list(paths.keys())[:20]}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_11_check_endpoint_requires_valid_body() -> None:
    """BEH-11: POST /authz/opa/check with missing required fields returns 422."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        opa_client_mod = importlib.import_module("app.authz.opa_client")
        mock = _mock_opa_client(allow=True)
        app.dependency_overrides[opa_client_mod.get_opa_client] = lambda: mock

        # Missing required fields (subject, action, resource)
        r = await client.post("/api/v1/authz/opa/check", json={"context": {}})
        assert r.status_code == 422, f"Expected 422, got: {r.status_code}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_12_generated_py_all_parse() -> None:
    """BEH-12: All generated .py files under app/authz/ AST-parse cleanly."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        authz_dir = project_dir / "app" / "authz"
        for py_file in sorted(authz_dir.rglob("*.py")):
            try:
                ast.parse(py_file.read_text())
            except SyntaxError as exc:
                raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_13_config_fields_present() -> None:
    """BEH-13: Settings class has OPA_URL, OPA_ENABLED after tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        config_content = (project_dir / "app" / "core" / "config.py").read_text()
        assert "OPA_URL" in config_content
        assert "OPA_ENABLED" in config_content
        assert "OPA_POLICY_PATH" in config_content
    finally:
        await _teardown(app, client, session, engine)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_beh_01_app_boots,
        test_beh_02_check_endpoint_allow,
        test_beh_03_check_endpoint_deny,
        test_beh_04_health_ok,
        test_beh_05_health_unavailable,
        test_beh_06_opa_models_importable,
        test_beh_07_opa_client_importable,
        test_beh_08_circuit_breaker_open_returns_decision,
        test_beh_09_opa_authz_init_exports,
        test_beh_10_openapi_has_opa_paths,
        test_beh_11_check_endpoint_requires_valid_body,
        test_beh_12_generated_py_all_parse,
        test_beh_13_config_fields_present,
    ]
    passed = failed = 0
    for t in tests:
        try:
            asyncio.run(t())
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            import traceback
            print(f"  FAIL  {t.__name__}: {exc}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)
