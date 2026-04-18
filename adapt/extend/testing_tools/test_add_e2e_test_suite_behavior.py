"""Behavior tests for TOOL-094 add_e2e_test_suite.

Proves that:
1. The app boots cleanly after the tool patches config.py.
2. GET /healthz returns 200.
3. Generated E2E test files AST-parse without errors.
4. Generated conftest.py uses ASGITransport (no real server).
5. All generated functions remain <= 50 LOC.
6. Config fields have correct 4-space indent.
7. No ruff F401 dead imports in the tool source.
8. Lazy-import verification on tool source.

Patches applied (so tests run without Docker):
- app/core/db.py            → SQLite + aiosqlite (no Postgres)
- app/middleware/idempotency.py → pass-through stub (no Redis)
- REDIS_URL env var          → removed

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_e2e_test_suite_behavior.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_e2e_test_suite_behavior.py
"""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_e2e_test_suite import add_e2e_test_suite
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_SQLITE_DB_PY = textwrap.dedent("""\
    \"\"\"Patched db.py — SQLite+aiosqlite, no Docker required.\"\"\"
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False,
                                  connect_args={"check_same_thread": False})

    async def init_db() -> None:
        \"\"\"Run startup checks.\"\"\"
        async with engine.begin() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))

    __all__ = ["engine", "init_db"]
""")

_IDEMPOTENCY_STUB_PY = textwrap.dedent("""\
    \"\"\"Pass-through idempotency middleware stub for tests.\"\"\"
    from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
    from starlette.requests import Request
    from starlette.responses import Response

    class IdempotencyMiddleware(BaseHTTPMiddleware):
        \"\"\"Pass-through stub — no Redis required.\"\"\"
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            \"\"\"Forward all requests without idempotency checking.\"\"\"
            return await call_next(request)
""")


@pytest.fixture(scope="module")
def behavior_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a fixture project with add_e2e_test_suite applied.

    Returns:
        Project root with SQLite patch, idempotency stub, and tool applied.
    """
    tmp = tmp_path_factory.mktemp("e2e_behavior")
    project_dir = create_fixture_project(name="e2e_behavior", tmp_dir=tmp)

    result = add_e2e_test_suite(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_e2e_test_suite failed in fixture setup: {result.error}"
    )

    db_file = project_dir / "app" / "core" / "db.py"
    db_file.write_text(_SQLITE_DB_PY)

    idempotency_file = project_dir / "app" / "middleware" / "idempotency.py"
    if idempotency_file.exists():
        idempotency_file.write_text(_IDEMPOTENCY_STUB_PY)

    os.environ.pop("REDIS_URL", None)

    return project_dir


@pytest.fixture(scope="module")
def booted_app(behavior_project: Path):
    """Import the ASGI app from the behavior_project.

    Returns:
        The FastAPI app instance.
    """
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)

    _clear_modules()

    app_module = importlib.import_module("app.main")
    app = app_module.app

    yield app

    _clear_modules()
    if project_str in sys.path:
        sys.path.remove(project_str)


def _clear_modules() -> None:
    """Remove cached app.* modules from sys.modules."""
    to_remove = [k for k in sys.modules if k.startswith("app")]
    for key in to_remove:
        del sys.modules[key]


@pytest_asyncio.fixture
async def client(booted_app):
    """Yield an async httpx client backed by the ASGI app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=booted_app),
        base_url="http://test",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# B-01: GET /healthz → 200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_healthz_returns_200(client: httpx.AsyncClient) -> None:
    """GET /healthz returns 200 — proves app boots after E2E config patch."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200, (
        f"Expected 200 from /healthz after e2e suite patch, "
        f"got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B-02: E2E test files AST-parse without errors
# ---------------------------------------------------------------------------

def test_generated_e2e_files_ast_parse(behavior_project: Path) -> None:
    """All generated tests/e2e/*.py files pass ast.parse."""
    e2e_dir = behavior_project / "tests" / "e2e"
    assert e2e_dir.exists(), "tests/e2e/ directory not created"
    py_files = list(e2e_dir.glob("*.py"))
    assert len(py_files) >= 4, f"Expected >= 4 py files in tests/e2e/, got {len(py_files)}"
    for py_file in py_files:
        try:
            ast.parse(py_file.read_text())
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError in {py_file}: {exc}")


# ---------------------------------------------------------------------------
# B-03: conftest.py uses ASGITransport
# ---------------------------------------------------------------------------

def test_conftest_uses_asgi_transport(behavior_project: Path) -> None:
    """conftest.py uses httpx.ASGITransport — no real HTTP server required."""
    conftest = behavior_project / "tests" / "e2e" / "conftest.py"
    content = conftest.read_text()
    assert "ASGITransport" in content, (
        "conftest.py must use httpx.ASGITransport (in-process ASGI, no server)"
    )


# ---------------------------------------------------------------------------
# B-04: All generated functions <= 50 LOC
# ---------------------------------------------------------------------------

def test_all_generated_functions_under_50_loc(behavior_project: Path) -> None:
    """No function in tests/e2e/ generated by the tool exceeds 50 LOC."""
    e2e_dir = behavior_project / "tests" / "e2e"
    max_loc = 0
    worst_fn = ""
    for py_file in sorted(e2e_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    if loc > max_loc:
                        max_loc = loc
                        worst_fn = f"{py_file}:{node.name} ({loc} LOC)"
    assert max_loc <= 50, f"Function exceeds 50 LOC: {worst_fn}"


# ---------------------------------------------------------------------------
# B-05: Config fields have 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_four_space_indent(behavior_project: Path) -> None:
    """E2E_* fields in config.py are inside Settings class (4-space indent)."""
    config_file = behavior_project / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("E2E_BASE_URL", "E2E_TEST_EMAIL", "E2E_TEST_PASSWORD"):
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), (
                    f"{field} not at 4-space indent: {line!r}"
                )
                break
        else:
            pytest.fail(f"{field} not found in config.py at all")


# ---------------------------------------------------------------------------
# B-06: Ruff F401 clean on tool source
# ---------------------------------------------------------------------------

def test_ruff_f401_clean_on_tool_source() -> None:
    """The tool source file has no unused imports (ruff F401)."""
    tool_file = Path(__file__).parent / "add_e2e_test_suite.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(tool_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 found dead imports in add_e2e_test_suite.py:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# B-07: Lazy-import verification on tool source
# ---------------------------------------------------------------------------

def test_no_top_level_optional_sdk_imports() -> None:
    """The tool file has no top-level optional SDK imports."""
    tool_file = Path(__file__).parent / "add_e2e_test_suite.py"
    tree = ast.parse(tool_file.read_text())
    top_level_imports = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    optional_sdks = {"playwright", "selenium", "locust", "k6"}
    for node in top_level_imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in optional_sdks, (
                    f"Optional SDK '{alias.name}' imported at module level"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in optional_sdks, (
                f"Optional SDK '{node.module}' imported at module level"
            )


# ---------------------------------------------------------------------------
# B-08: E2E_* config fields importable at runtime
# ---------------------------------------------------------------------------

def test_e2e_config_fields_importable(behavior_project: Path) -> None:
    """app/core/config.py with E2E_* fields imports without error."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        config_mod = importlib.import_module("app.core.config")
        settings = config_mod.settings
        assert hasattr(settings, "E2E_BASE_URL"), "settings missing E2E_BASE_URL"
        assert hasattr(settings, "E2E_TEST_EMAIL"), "settings missing E2E_TEST_EMAIL"
        assert hasattr(settings, "E2E_TEST_PASSWORD"), "settings missing E2E_TEST_PASSWORD"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sync_tests = [
        test_ruff_f401_clean_on_tool_source,
        test_no_top_level_optional_sdk_imports,
    ]

    passed = failed = 0
    for test_fn in sync_tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-094 behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
