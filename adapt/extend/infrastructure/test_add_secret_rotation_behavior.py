"""BEHAVIOR TEST — TOOL-114 add_secret_rotation.

Proves that the generated code works at RUNTIME: boots a real ASGI app,
and asserts structural / config correctness without external services.

Patches applied:
- ``app/core/db.py``              → SQLite + aiosqlite
- ``app/middleware/idempotency.py`` → pass-through stub (no Redis)
- ``REDIS_URL`` env var           → removed

Run::

    PYTHONPATH=. .venv/bin/pytest adapt/extend/infrastructure/test_add_secret_rotation_behavior.py -v

or standalone::

    PYTHONPATH=. .venv/bin/python adapt/extend/infrastructure/test_add_secret_rotation_behavior.py
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Environment setup — MUST happen before any app import
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-secret-rotation-key-32+!")
os.environ.setdefault("SECRET_PROVIDER", "env")
os.environ.setdefault("VAULT_URL", "")
os.environ.setdefault("VAULT_TOKEN", "")
os.environ.setdefault("SECRET_ROTATION_INTERVAL_H", "24")
os.environ.pop("REDIS_URL", None)

import ast
import importlib
import sys
import textwrap
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_secret_rotation import add_secret_rotation
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Patch templates
# ---------------------------------------------------------------------------

_SQLITE_DB_PY = textwrap.dedent("""\
    \"\"\"Patched db.py — SQLite+aiosqlite, no Docker required.\"\"\"

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )


    async def init_db() -> None:
        \"\"\"Run startup checks (connection test).\"\"\"
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))


    __all__ = ["engine", "init_db"]
""")

_PASSTHROUGH_IDEMPOTENCY_PY = textwrap.dedent("""\
    \"\"\"Patched idempotency.py — pass-through stub (no Redis).\"\"\"

    from __future__ import annotations

    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response


    class IdempotencyMiddleware(BaseHTTPMiddleware):
        \"\"\"No-op pass-through stub for testing without Redis.\"\"\"

        async def dispatch(
            self,
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            return await call_next(request)
""")


def _patch_project(project_dir: Path) -> None:
    (project_dir / "app" / "core" / "db.py").write_text(_SQLITE_DB_PY)
    idempotency_path = project_dir / "app" / "middleware" / "idempotency.py"
    if idempotency_path.exists():
        idempotency_path.write_text(_PASSTHROUGH_IDEMPOTENCY_PY)


def _load_app(project_dir: Path) -> Any:
    _orig_path = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    stale = [k for k in sys.modules if k == "app" or k.startswith("app.")]
    for key in stale:
        del sys.modules[key]
    try:
        app_module = importlib.import_module("app.main")
    finally:
        sys.path[:] = _orig_path
    return app_module.app


def _setup_project() -> tuple[Path, Any]:
    project_dir = create_fixture_project(name="rot_behavior")
    result = add_secret_rotation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_secret_rotation failed: {result.error}\nnotes: {result.notes}"
    )
    _patch_project(project_dir)
    asgi_app = _load_app(project_dir)
    return project_dir, asgi_app


# ---------------------------------------------------------------------------
# Module-level shared state
# ---------------------------------------------------------------------------

_PROJECT_DIR: Path | None = None
_ASGI_APP: Any = None


def _get_shared_app() -> tuple[Path, Any]:
    global _PROJECT_DIR, _ASGI_APP
    if _PROJECT_DIR is None:
        _PROJECT_DIR, _ASGI_APP = _setup_project()
    return _PROJECT_DIR, _ASGI_APP


@pytest.fixture(scope="module")
def project_dir_and_app() -> tuple[Path, Any]:
    return _get_shared_app()


@pytest.fixture(scope="module")
def project_dir(project_dir_and_app: tuple[Path, Any]) -> Path:
    return project_dir_and_app[0]


@pytest.fixture(scope="module")
def asgi_app(project_dir_and_app: tuple[Path, Any]) -> Any:
    return project_dir_and_app[1]


# ---------------------------------------------------------------------------
# B-01: GET /healthz → 200
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b01_healthz_returns_200(asgi_app: Any) -> None:
    """B-01: App boots cleanly after secret rotation tool applied."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-02: hvac NOT imported at top level
# ---------------------------------------------------------------------------

def test_b02_hvac_not_top_level(project_dir: Path) -> None:
    """B-02: hvac is NOT imported at module top level in secret_rotation.py."""
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    assert rotation_file.exists(), "secret_rotation.py missing"
    tree = ast.parse(rotation_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "hvac", "hvac at top level"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "hvac", "hvac at top level via 'from'"


# ---------------------------------------------------------------------------
# B-03: boto3 NOT imported at top level
# ---------------------------------------------------------------------------

def test_b03_boto3_not_top_level(project_dir: Path) -> None:
    """B-03: boto3 is NOT imported at module top level in secret_rotation.py."""
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    tree = ast.parse(rotation_file.read_text())
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "boto3", "boto3 at top level"
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "") != "boto3", "boto3 at top level via 'from'"


# ---------------------------------------------------------------------------
# B-04: leak_detector.py importable
# ---------------------------------------------------------------------------

def test_b04_leak_detector_importable(project_dir: Path) -> None:
    """B-04: app/middleware/leak_detector.py is importable without raising."""
    leak_file = project_dir / "app" / "middleware" / "leak_detector.py"
    assert leak_file.exists(), "leak_detector.py missing"

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "app.middleware.leak_detector_behavior", str(leak_file)
    )
    assert spec is not None and spec.loader is not None

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception as exc:
        raise AssertionError(f"leak_detector.py raised on import: {exc}") from exc
    finally:
        sys.path[:] = _orig

    assert hasattr(module, "LeakDetectorMiddleware"), "LeakDetectorMiddleware not found"


# ---------------------------------------------------------------------------
# B-05: config fields 4-space indent
# ---------------------------------------------------------------------------

def test_b05_config_fields_4space_indent(project_dir: Path) -> None:
    """B-05: SECRET_PROVIDER is inside the Settings class (4-space indent)."""
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for line in content.splitlines():
        if "SECRET_PROVIDER" in line and ":" in line:
            assert line.startswith("    "), f"Not 4-space indented: {line!r}"
            break
    else:
        raise AssertionError("SECRET_PROVIDER not found in config.py")


# ---------------------------------------------------------------------------
# B-06: rotate_secrets.py CLI importable
# ---------------------------------------------------------------------------

def test_b06_rotate_secrets_cli_importable(project_dir: Path) -> None:
    """B-06: scripts/rotate_secrets.py is importable and has main()."""
    cli_file = project_dir / "scripts" / "rotate_secrets.py"
    assert cli_file.exists(), "scripts/rotate_secrets.py missing"

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "rotate_secrets_behavior", str(cli_file)
    )
    assert spec is not None and spec.loader is not None

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except SystemExit:
        pass  # argparse may call sys.exit on import with no args
    except Exception as exc:
        raise AssertionError(f"rotate_secrets.py raised on import: {exc}") from exc
    finally:
        sys.path[:] = _orig

    assert hasattr(module, "main"), "main() not found in rotate_secrets.py"


# ---------------------------------------------------------------------------
# B-07: all functions in generated app/ ≤50 LOC
# ---------------------------------------------------------------------------

def test_b07_no_function_over_50_loc(project_dir: Path) -> None:
    """B-07: No function in app/ exceeds 50 LOC."""
    app_dir = project_dir / "app"
    for py_file in sorted(app_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    assert loc <= 50, (
                        f"{py_file.name}:{node.name} has {loc} LOC (limit: 50)"
                    )


# ---------------------------------------------------------------------------
# B-08: validate_secrets_at_startup callable at runtime
# ---------------------------------------------------------------------------

def test_b08_validate_secrets_callable(project_dir: Path) -> None:
    """B-08: validate_secrets_at_startup exists and is callable."""
    rotation_file = project_dir / "app" / "core" / "secret_rotation.py"
    assert "validate_secrets_at_startup" in rotation_file.read_text(), (
        "validate_secrets_at_startup not found"
    )

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "app.core.secret_rotation_behavior", str(rotation_file)
    )
    assert spec is not None and spec.loader is not None

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception as exc:
        raise AssertionError(
            f"secret_rotation.py raised on import: {exc}"
        ) from exc
    finally:
        sys.path[:] = _orig

    assert hasattr(module, "validate_secrets_at_startup"), (
        "validate_secrets_at_startup not found after import"
    )
    assert callable(module.validate_secrets_at_startup), (
        "validate_secrets_at_startup is not callable"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import anyio

    tests_sync = [
        test_b02_hvac_not_top_level,
        test_b03_boto3_not_top_level,
        test_b04_leak_detector_importable,
        test_b05_config_fields_4space_indent,
        test_b06_rotate_secrets_cli_importable,
        test_b07_no_function_over_50_loc,
        test_b08_validate_secrets_callable,
    ]
    tests_async = [
        test_b01_healthz_returns_200,
    ]

    project_dir, asgi_app = _get_shared_app()

    passed = failed = 0
    for test_fn in tests_async:
        try:
            anyio.run(test_fn, asgi_app)
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    for test_fn in tests_sync:
        try:
            test_fn(project_dir)
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-114 behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
