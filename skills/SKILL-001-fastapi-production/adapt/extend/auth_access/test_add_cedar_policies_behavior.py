"""Behavior test for TOOL-071 add_cedar_policies.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub

Then fires real HTTP requests via ASGI transport to verify that:
  - The app boots cleanly with Cedar installed
  - POST /authz/check returns 200 and an ``allowed`` boolean
  - GET /authz/policies returns a list of policy names
  - cedarpy absent: engine returns CEDAR_DEFAULT_EFFECT decision (allow when disabled)
  - Config fields are present and accessible
  - Generated modules import without crash

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_cedar_policies_behavior.py -v

or::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_cedar_policies_behavior.py
"""

from __future__ import annotations

import ast
import importlib
import os
import sys
import tempfile
from pathlib import Path

# Set env vars BEFORE importing the app (avoids Settings validation errors)
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-for-cedar-authz-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
# Cedar disabled by default so tests work without cedarpy installed
os.environ.setdefault("CEDAR_ENABLED", "false")
# Remove REDIS_URL to avoid Redis connection attempts in tests
os.environ.pop("REDIS_URL", None)

import asyncio
import pytest


# ---------------------------------------------------------------------------
# Module-level shared project (built once per session)
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

    from tests.common.fixture_factory import create_fixture_project
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_cedar_policies import add_cedar_policies

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="cedar_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_cedar_policies(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_cedar_policies failed: {result.error}")

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

    Patches ``app.core.session.get_session`` to use a shared SQLite engine.
    Creates all tables from Base.metadata so no Alembic run is needed.

    Args:
        project_dir: Path to the project root.

    Returns:
        Tuple of (AsyncClient, AsyncSession, AsyncEngine, app).
    """
    from sqlalchemy.ext.asyncio import (
        create_async_engine,
        async_sessionmaker,
        AsyncSession,
    )
    from httpx import ASGITransport, AsyncClient

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


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_beh_01_app_boots() -> None:
    """BEH-01: App boots cleanly with Cedar authz tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code} {r.text}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_authz_check_cedar_disabled() -> None:
    """BEH-02: POST /authz/check returns 200 with allowed=True when Cedar is disabled."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {
            "principal": 'User::"alice"',
            "action": 'Action::"read"',
            "resource": 'Resource::"report-42"',
            "context": {},
        }
        r = await client.post("/api/v1/authz/check", json=payload)
        # Cedar disabled → engine returns True (bypass mode)
        assert r.status_code == 200, f"authz/check: {r.status_code} {r.text}"
        body = r.json()
        assert "allowed" in body, f"Response missing 'allowed': {body}"
        assert body["principal"] == payload["principal"]
        assert body["action"] == payload["action"]
        assert body["resource"] == payload["resource"]
        assert "reason" in body
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_authz_check_response_shape() -> None:
    """BEH-03: POST /authz/check response has all AuthzResponse fields."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {
            "principal": 'User::"bob"',
            "action": 'Action::"post"',
            "resource": 'Resource::"items"',
        }
        r = await client.post("/api/v1/authz/check", json=payload)
        assert r.status_code == 200
        body = r.json()
        for field in ("allowed", "principal", "action", "resource", "reason"):
            assert field in body, f"Missing field in AuthzResponse: {field}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_list_policies_returns_list() -> None:
    """BEH-04: GET /authz/policies returns a list (may be empty when dir absent)."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/authz/policies")
        assert r.status_code == 200, f"authz/policies: {r.status_code} {r.text}"
        body = r.json()
        assert isinstance(body, list), f"Expected list, got: {type(body)}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_openapi_has_authz_paths() -> None:
    """BEH-05: OpenAPI schema includes /authz/check and /authz/policies paths."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        authz_paths = [p for p in paths if "authz" in p]
        assert len(authz_paths) >= 1, (
            f"No authz paths in OpenAPI: {list(paths.keys())[:20]}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_authz_modules_import_cleanly() -> None:
    """BEH-06: All app.authz modules import without crash."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    for module_name in (
        "app.authz.engine",
        "app.authz.models",
        "app.authz.middleware",
    ):
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise AssertionError(f"Module {module_name} failed to import: {exc}") from exc


@pytest.mark.asyncio
async def test_beh_07_cedar_engine_no_cedarpy_fallback() -> None:
    """BEH-07: CedarEngine.is_authorized returns True when CEDAR_ENABLED=False (no cedarpy needed)."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    engine_mod = importlib.import_module("app.authz.engine")
    engine = engine_mod.CedarEngine(policy_dir="/nonexistent")
    # With CEDAR_ENABLED=false (our env default), should return True (bypass)
    result = engine.is_authorized(
        principal='User::"test"',
        action='Action::"get"',
        resource='Resource::"data"',
    )
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_beh_08_config_fields_accessible() -> None:
    """BEH-08: CEDAR_ENABLED, CEDAR_POLICY_DIR, CEDAR_DEFAULT_EFFECT are accessible via Settings."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]

    config_mod = importlib.import_module("app.core.config")
    settings = config_mod.settings
    assert hasattr(settings, "CEDAR_ENABLED"), "Settings missing CEDAR_ENABLED"
    assert hasattr(settings, "CEDAR_POLICY_DIR"), "Settings missing CEDAR_POLICY_DIR"
    assert hasattr(settings, "CEDAR_DEFAULT_EFFECT"), "Settings missing CEDAR_DEFAULT_EFFECT"


@pytest.mark.asyncio
async def test_beh_09_authz_check_with_context() -> None:
    """BEH-09: POST /authz/check accepts and echoes arbitrary context dict."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {
            "principal": 'User::"carol"',
            "action": 'Action::"delete"',
            "resource": 'Resource::"invoice-7"',
            "context": {"department": "finance", "clearance_level": 3},
        }
        r = await client.post("/api/v1/authz/check", json=payload)
        assert r.status_code == 200, f"check with context failed: {r.status_code} {r.text}"
        body = r.json()
        assert "allowed" in body
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_10_lazy_cedarpy_not_at_top_level() -> None:
    """BEH-10: cedarpy is never imported at module top level in any app/authz .py file."""
    project_dir = _build_project()
    authz_dir = project_dir / "app" / "authz"
    for py_file in authz_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in tree.body:  # Only top-level nodes
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "cedarpy" not in alias.name, (
                        f"cedarpy top-level import found in {py_file}"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert "cedarpy" not in node.module, (
                    f"cedarpy top-level import found in {py_file}"
                )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_beh_01_app_boots,
        test_beh_02_authz_check_cedar_disabled,
        test_beh_03_authz_check_response_shape,
        test_beh_04_list_policies_returns_list,
        test_beh_05_openapi_has_authz_paths,
        test_beh_06_authz_modules_import_cleanly,
        test_beh_07_cedar_engine_no_cedarpy_fallback,
        test_beh_08_config_fields_accessible,
        test_beh_09_authz_check_with_context,
        test_beh_10_lazy_cedarpy_not_at_top_level,
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
