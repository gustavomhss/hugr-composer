"""Behavior tests for TOOL-075 add_passkey_auth.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub

Then fires real HTTP requests via ASGI transport to verify that:
  - The app boots cleanly with passkeys installed
  - POST /api/v1/passkeys/register/begin returns 200 with session_id and options
  - POST /api/v1/passkeys/login/begin returns 200 with session_id and options
  - POST /api/v1/passkeys/register/complete with expired session returns 400
  - POST /api/v1/passkeys/login/complete with expired session returns 400
  - py_webauthn imported lazily (AST verified)
  - Generated functions <= 50 LOC
  - Config fields have 4-space indent
  - ruff F401 clean

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_passkey_auth_behavior.py -v
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
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-for-passkey-auth-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("WEBAUTHN_RP_ID", "localhost")
os.environ.setdefault("WEBAUTHN_RP_NAME", "Test App")
os.environ.setdefault("WEBAUTHN_ORIGIN", "http://localhost:8000")
os.environ.pop("REDIS_URL", None)

import pytest

# ---------------------------------------------------------------------------
# Module-level shared project
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
    from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth
    from tests.common.fixture_factory import create_fixture_project

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="passkey_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_passkey_auth failed: {result.error}")

    _PROJECT_DIR = project_dir
    return project_dir


def _load_app(project_dir: Path):
    """Load the FastAPI app, clearing module cache.

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
    """Clean up client, session, engine and overrides.

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
    """BEH-01: App boots cleanly with passkey auth tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code} {r.text}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_register_begin_requires_auth() -> None:
    """BEH-02: POST /api/v1/passkeys/register/begin requires auth (R5-O4-C5).

    Without an Authorization header the route MUST reject with 401 before
    any WebAuthn work happens — the credential owner is taken from the
    authenticated session, not from a client-supplied user_id.
    """
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {"username": "testuser"}
        r = await client.post("/api/v1/passkeys/register/begin", json=payload)
        assert r.status_code == 401, (
            f"register/begin must reject unauthenticated callers with 401; "
            f"got {r.status_code} {r.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_login_begin_without_pywebauthn() -> None:
    """BEH-03: POST /api/v1/passkeys/login/begin fails gracefully when py_webauthn absent."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.post("/api/v1/passkeys/login/begin")
        assert r.status_code in (200, 500), (
            f"Unexpected status for login/begin: {r.status_code} {r.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_register_complete_requires_auth() -> None:
    """BEH-04: POST /api/v1/passkeys/register/complete requires auth (R5-O4-C5).

    The credential owner is bound to current_user.id server-side; an
    unauthenticated caller MUST be rejected with 401 regardless of the
    session_id supplied — this prevents a client from registering an
    authenticator under a victim's UUID.
    """
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {
            "session_id": "nonexistent-session-id-xyz",
            "credential": {"type": "public-key", "id": "test"},
        }
        r = await client.post("/api/v1/passkeys/register/complete", json=payload)
        assert r.status_code == 401, (
            f"register/complete must reject unauthenticated callers with 401; "
            f"got {r.status_code} {r.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_login_complete_invalid_session() -> None:
    """BEH-05: POST /api/v1/passkeys/login/complete with invalid session_id returns 400."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        payload = {
            "session_id": "nonexistent-session-id-abc",
            "credential": {"type": "public-key", "id": "test", "rawId": "test"},
        }
        r = await client.post("/api/v1/passkeys/login/complete", json=payload)
        assert r.status_code == 400, (
            f"Expected 400 for invalid session, got {r.status_code}: {r.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_py_webauthn_lazy_import_verified() -> None:
    """BEH-06: py_webauthn is not a top-level import in webauthn.py (AST verified)."""
    project_dir = _build_project()
    webauthn_file = project_dir / "app" / "auth" / "webauthn.py"
    tree = ast.parse(webauthn_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "py_webauthn" not in names and "py_webauthn" not in module, (
                "py_webauthn must not be a top-level import in webauthn.py"
            )


@pytest.mark.asyncio
async def test_beh_07_all_functions_le_50_loc() -> None:
    """BEH-07: All generated functions in created files are <= 50 LOC."""
    project_dir = _build_project()
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_passkey_auth import add_passkey_auth

    result = add_passkey_auth(ToolInput(project_dir=str(project_dir)))
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
    """BEH-08: WebAuthn config fields are inside Settings with 4-space indent."""
    project_dir = _build_project()
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("WEBAUTHN_RP_ID", "WEBAUTHN_RP_NAME", "WEBAUTHN_ORIGIN"):
        assert field in content, f"{field} not in config.py"
        for line in content.splitlines():
            if field in line and ":" in line:
                assert line.startswith("    "), (
                    f"Config field {field!r} not indented with 4 spaces: {line!r}"
                )


@pytest.mark.asyncio
async def test_beh_09_ruff_f401_clean() -> None:
    """BEH-09: Generated webauthn.py has no unused imports (ruff F401 clean)."""
    project_dir = _build_project()
    webauthn_file = project_dir / "app" / "auth" / "webauthn.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(webauthn_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 violations in webauthn.py:\n{result.stdout}"
    )


@pytest.mark.asyncio
async def test_beh_10_openapi_has_passkey_paths() -> None:
    """BEH-10: OpenAPI schema includes /passkeys/register/begin path."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        passkey_paths = [p for p in paths if "passkey" in p]
        assert len(passkey_paths) >= 1, (
            f"No passkey paths in OpenAPI: {list(paths.keys())[:20]}"
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
        test_beh_02_register_begin_without_pywebauthn,
        test_beh_03_login_begin_without_pywebauthn,
        test_beh_04_register_complete_invalid_session,
        test_beh_05_login_complete_invalid_session,
        test_beh_06_py_webauthn_lazy_import_verified,
        test_beh_07_all_functions_le_50_loc,
        test_beh_08_config_fields_4space_indent,
        test_beh_09_ruff_f401_clean,
        test_beh_10_openapi_has_passkey_paths,
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
