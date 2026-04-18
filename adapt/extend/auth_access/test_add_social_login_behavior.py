"""Behavior tests for TOOL-074 add_social_login.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub

Then fires real HTTP requests via ASGI transport to verify that:
  - The app boots cleanly with social login installed
  - GET /api/v1/auth/google/login redirects (302)
  - GET /api/v1/auth/{unknown}/login returns 400
  - Unsafe return_to is rejected (400)
  - Config fields accessible via settings
  - httpx imported lazily (AST verified)
  - Generated functions <= 50 LOC
  - Config fields have 4-space indent
  - ruff F401 clean

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_social_login_behavior.py -v
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-for-social-login-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("SOCIAL_LOGIN_CALLBACK_BASE_URL", "http://test")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id")
os.environ.setdefault("GITHUB_CLIENT_ID", "test-github-client-id")
os.environ.pop("REDIS_URL", None)

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
    from adapt.extend.auth_access.add_social_login import add_social_login

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="social_login_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_social_login failed: {result.error}")

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
    """BEH-01: App boots cleanly with social login tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code} {r.text}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_google_login_redirects() -> None:
    """BEH-02: GET /api/v1/auth/google/login returns a redirect (302) to Google."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/auth/google/login", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308), (
            f"Expected redirect for /api/v1/auth/google/login, got {r.status_code}"
        )
        location = r.headers.get("location", "")
        assert "google" in location.lower() or "accounts.google" in location.lower(), (
            f"Redirect location doesn't point to Google: {location}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_unknown_provider_returns_400() -> None:
    """BEH-03: GET /api/v1/auth/unknown/login returns 400 for unrecognized provider."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/auth/unknownprovider/login", follow_redirects=False)
        assert r.status_code == 400, (
            f"Expected 400 for unknown provider, got {r.status_code}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_unsafe_return_to_rejected() -> None:
    """BEH-04: GET /api/v1/auth/google/login with return_to=http://evil.com returns 400."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get(
            "/api/v1/auth/google/login",
            params={"return_to": "http://evil.com/steal"},
            follow_redirects=False,
        )
        assert r.status_code == 400, (
            f"Expected 400 for unsafe return_to, got {r.status_code}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_openapi_has_social_paths() -> None:
    """BEH-05: OpenAPI schema includes /auth/{provider}/login path."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        social_paths = [p for p in paths if "login" in p or "callback" in p]
        assert len(social_paths) >= 1, (
            f"No social auth paths in OpenAPI: {list(paths.keys())[:20]}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_httpx_lazy_import_verified() -> None:
    """BEH-06: httpx is not a top-level import in app/auth/social.py (AST verified)."""
    project_dir = _build_project()
    key = str(project_dir)
    if key not in sys.path:
        sys.path.insert(0, key)
    social_file = project_dir / "app" / "auth" / "social.py"
    tree = ast.parse(social_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "httpx" not in names and "httpx" not in module, (
                "httpx must not be a top-level import in social.py"
            )


@pytest.mark.asyncio
async def test_beh_07_all_functions_le_50_loc() -> None:
    """BEH-07: All generated functions in created files are <= 50 LOC."""
    project_dir = _build_project()
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_social_login import add_social_login

    result = add_social_login(ToolInput(project_dir=str(project_dir)))
    created = getattr(result, "files_created", [])
    for path_str in created:
        p = Path(path_str)
        if p.suffix != ".py" or not p.is_file():
            continue
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno"):
                    loc = node.end_lineno - node.lineno + 1
                    assert loc <= 50, (
                        f"Function {node.name!r} in {p.name} has {loc} LOC (max 50)"
                    )


@pytest.mark.asyncio
async def test_beh_08_config_fields_4space_indent() -> None:
    """BEH-08: Social login config fields are inside Settings with 4-space indent."""
    project_dir = _build_project()
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("GOOGLE_CLIENT_ID", "GITHUB_CLIENT_ID", "APPLE_CLIENT_ID"):
        assert field in content, f"{field} not in config.py"
        for line in content.splitlines():
            if field in line and ":" in line:
                assert line.startswith("    "), (
                    f"Config field {field!r} not indented with 4 spaces: {line!r}"
                )


@pytest.mark.asyncio
async def test_beh_09_ruff_f401_clean() -> None:
    """BEH-09: Generated social.py has no unused imports (ruff F401 clean)."""
    project_dir = _build_project()
    social_file = project_dir / "app" / "auth" / "social.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(social_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 violations in social.py:\n{result.stdout}"
    )


@pytest.mark.asyncio
async def test_beh_10_github_login_redirects() -> None:
    """BEH-10: GET /api/v1/auth/github/login returns a redirect to GitHub."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/auth/github/login", follow_redirects=False)
        assert r.status_code in (301, 302, 307, 308), (
            f"Expected redirect for /api/v1/auth/github/login, got {r.status_code}"
        )
        location = r.headers.get("location", "")
        assert "github" in location.lower(), (
            f"Redirect location doesn't point to GitHub: {location}"
        )
    finally:
        await _teardown(app, client, session, engine)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import asyncio

    tests = [
        test_beh_01_app_boots,
        test_beh_02_google_login_redirects,
        test_beh_03_unknown_provider_returns_400,
        test_beh_04_unsafe_return_to_rejected,
        test_beh_05_openapi_has_social_paths,
        test_beh_06_httpx_lazy_import_verified,
        test_beh_07_all_functions_le_50_loc,
        test_beh_08_config_fields_4space_indent,
        test_beh_09_ruff_f401_clean,
        test_beh_10_github_login_redirects,
    ]

    passed = 0
    failed = 0

    for t in tests:
        try:
            asyncio.run(t())
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
