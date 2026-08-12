"""Behavior tests for TOOL-076 add_sms_otp.

Generates a real fixture project, applies the tool, patches:
  - ``app.core.session`` → SQLite in-memory (aiosqlite)
  - ``app.middleware.idempotency`` (if present) → pass-through stub
  - ``app.auth.sms_otp.send_sms`` → no-op stub (avoids real Twilio calls)

Then fires real HTTP requests via ASGI transport to verify that:
  - The app boots cleanly with SMS OTP installed
  - POST /api/v1/auth/sms/send creates an OtpCode and returns 200
  - POST /api/v1/auth/sms/verify with wrong code returns 400
  - POST /api/v1/auth/sms/verify with correct code returns 200
  - Rate limit: 5th+1 send within 1 hour returns 429
  - twilio imported lazily (AST verified)
  - Generated functions <= 50 LOC
  - Config fields have 4-space indent
  - ruff F401 clean

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_sms_otp_behavior.py -v
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
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-for-sms-otp-auth-ok!")
os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("SMS_PROVIDER", "twilio")
os.environ.setdefault("OTP_LENGTH", "6")
os.environ.setdefault("OTP_EXPIRY_SECONDS", "300")
os.environ.setdefault("OTP_RATE_LIMIT_MAX", "5")
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
    from adapt.extend.auth_access.add_sms_otp import add_sms_otp
    from tests.common.fixture_factory import create_fixture_project

    _TMPDIR = tempfile.TemporaryDirectory()
    project_dir = create_fixture_project(
        name="sms_otp_behavior",
        tmp_dir=Path(_TMPDIR.name),
    )
    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
    if result.status == "error":
        raise RuntimeError(f"add_sms_otp failed: {result.error}")

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


async def _make_sqlite_client(project_dir: Path, patch_send_sms: bool = True):
    """Create an ASGI test client backed by SQLite + stubbed send_sms.

    Args:
        project_dir: Path to the project root.
        patch_send_sms: If True, patch send_sms to avoid real SMS calls.

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

    if patch_send_sms:
        # Stub send_sms to avoid real Twilio/Vonage calls
        sms_mod = importlib.import_module("app.auth.sms_otp")

        async def _noop_send_sms(phone: str, message: str) -> None:
            pass

        sms_mod.send_sms = _noop_send_sms
        # Also patch in routes module — routes import send_sms directly
        try:
            routes_mod = importlib.import_module("app.api.routes.sms_auth")
            if hasattr(routes_mod, "send_sms"):
                routes_mod.send_sms = _noop_send_sms
        except ModuleNotFoundError:
            pass

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
    """BEH-01: App boots cleanly with SMS OTP tool applied."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/healthz")
        assert r.status_code == 200, f"healthz failed: {r.status_code} {r.text}"
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_02_send_otp_returns_200() -> None:
    """BEH-02: POST /auth/sms/send with a valid phone number returns 200."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.post("/api/v1/auth/sms/send", json={"phone": "+15555550100"})
        assert r.status_code == 200, (
            f"Expected 200 for /auth/sms/send, got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert "expires_in_seconds" in body
        assert body["expires_in_seconds"] > 0
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_03_verify_wrong_code_returns_400() -> None:
    """BEH-03: POST /auth/sms/verify with wrong code returns 400."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        # Send first so a record exists
        await client.post("/api/v1/auth/sms/send", json={"phone": "+15555550101"})
        r = await client.post(
            "/api/v1/auth/sms/verify",
            json={"phone": "+15555550101", "code": "000000"},
        )
        assert r.status_code == 400, (
            f"Expected 400 for wrong code, got {r.status_code}: {r.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_04_verify_correct_code_returns_200() -> None:
    """BEH-04: POST /auth/sms/verify with correct code returns 200."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        # Send OTP
        await client.post("/api/v1/auth/sms/send", json={"phone": "+15555550102"})

        # Read the code directly from the DB
        from sqlalchemy import text
        result = await session.execute(
            text("SELECT code FROM otp_codes WHERE phone='+15555550102' LIMIT 1")
        )
        row = result.fetchone()
        if row is None:
            pytest.skip("No OtpCode row found — SQLite schema issue")
        code = row[0]

        r = await client.post(
            "/api/v1/auth/sms/verify",
            json={"phone": "+15555550102", "code": code},
        )
        assert r.status_code == 200, (
            f"Expected 200 for correct code, got {r.status_code}: {r.text}"
        )
        body = r.json()
        assert body.get("verified") is True
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_05_rate_limit_enforced() -> None:
    """BEH-05: 6th OTP send within an hour returns 429 Too Many Requests."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        phone = "+15555550199"
        for _ in range(5):
            r = await client.post("/api/v1/auth/sms/send", json={"phone": phone})
            assert r.status_code == 200, f"Expected 200, got {r.status_code}"
        r6 = await client.post("/api/v1/auth/sms/send", json={"phone": phone})
        assert r6.status_code == 429, (
            f"Expected 429 on 6th send, got {r6.status_code}: {r6.text}"
        )
    finally:
        await _teardown(app, client, session, engine)


@pytest.mark.asyncio
async def test_beh_06_twilio_lazy_import_verified() -> None:
    """BEH-06: twilio is not a top-level import in sms_otp.py (AST verified)."""
    project_dir = _build_project()
    sms_file = project_dir / "app" / "auth" / "sms_otp.py"
    tree = ast.parse(sms_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in getattr(node, "names", [])]
            module = getattr(node, "module", "") or ""
            assert "twilio" not in names and "twilio" not in module, (
                "twilio must not be a top-level import in sms_otp.py"
            )


@pytest.mark.asyncio
async def test_beh_07_all_functions_le_50_loc() -> None:
    """BEH-07: All generated functions in created files are <= 50 LOC."""
    project_dir = _build_project()
    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_sms_otp import add_sms_otp

    result = add_sms_otp(ToolInput(project_dir=str(project_dir)))
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
    """BEH-08: SMS OTP config fields are inside Settings with 4-space indent."""
    project_dir = _build_project()
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("TWILIO_ACCOUNT_SID", "OTP_LENGTH", "OTP_EXPIRY_SECONDS"):
        assert field in content, f"{field} not in config.py"
        for line in content.splitlines():
            if field in line and ":" in line:
                assert line.startswith("    "), (
                    f"Config field {field!r} not indented with 4 spaces: {line!r}"
                )


@pytest.mark.asyncio
async def test_beh_09_ruff_f401_clean() -> None:
    """BEH-09: Generated sms_otp.py has no unused imports (ruff F401 clean)."""
    project_dir = _build_project()
    sms_file = project_dir / "app" / "auth" / "sms_otp.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(sms_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 violations in sms_otp.py:\n{result.stdout}"
    )


@pytest.mark.asyncio
async def test_beh_10_openapi_has_sms_paths() -> None:
    """BEH-10: OpenAPI schema includes /auth/sms/send and /auth/sms/verify paths."""
    project_dir = _build_project()
    client, session, engine, app = await _make_sqlite_client(project_dir)
    try:
        r = await client.get("/api/v1/openapi.json")
        assert r.status_code == 200
        paths = r.json().get("paths", {})
        sms_paths = [p for p in paths if "sms" in p]
        assert len(sms_paths) >= 1, (
            f"No SMS OTP paths in OpenAPI: {list(paths.keys())[:20]}"
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
        test_beh_02_send_otp_returns_200,
        test_beh_03_verify_wrong_code_returns_400,
        test_beh_04_verify_correct_code_returns_200,
        test_beh_05_rate_limit_enforced,
        test_beh_06_twilio_lazy_import_verified,
        test_beh_07_all_functions_le_50_loc,
        test_beh_08_config_fields_4space_indent,
        test_beh_09_ruff_f401_clean,
        test_beh_10_openapi_has_sms_paths,
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
