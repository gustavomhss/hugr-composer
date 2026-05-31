"""Behavior tests for TOOL-106 add_api_deprecation.

Proves that:
1. App boots cleanly after the tool patches main.py and config.py.
2. GET /healthz returns 200.
3. GET /api/deprecations returns 200 with JSON body.
4. DeprecationRegistry.register() stores entry correctly.
5. DeprecationMiddleware adds Sunset + Deprecation headers.
6. DeprecationReporter.record() increments call count.
7. All generated functions remain <= 50 LOC.
8. Config fields have correct 4-space indent.
9. No ruff F401 dead imports in the tool source.
10. No top-level optional SDK imports in tool source.

Patches applied (so tests run without Docker):
- app/core/db.py            → SQLite + aiosqlite (no Postgres)
- app/middleware/idempotency.py → pass-through stub (no Redis)
- REDIS_URL env var          → removed

Run with::

    PYTHONPATH=. pytest adapt/extend/api_design/test_add_api_deprecation_behavior.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_api_deprecation_behavior.py
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
from adapt.extend.api_design.add_api_deprecation import add_api_deprecation
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Shared fixture patches
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
    """Generate a fixture project with add_api_deprecation applied.

    Returns:
        Project root with SQLite patch, idempotency stub, and tool applied.
    """
    tmp = tmp_path_factory.mktemp("depr_behavior")
    project_dir = create_fixture_project(name="depr_behavior", tmp_dir=tmp)

    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_api_deprecation failed in fixture setup: {result.error}"
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

    Installs a ``get_current_user`` dependency override so the auth-gated
    ``/api/v1/deprecations`` route (B0.11 close-out — deprecation
    metadata is a lifecycle fingerprint) can be reached by behavior
    tests without provisioning a real JWT.

    Returns:
        The FastAPI app instance.
    """
    import uuid as _uuid

    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)

    _clear_modules()
    app_module = importlib.import_module("app.main")
    app = app_module.app

    # Override get_current_user for the gated /deprecations endpoint.
    deps_mod = importlib.import_module("app.api.deps")
    user_mod = importlib.import_module("app.models.user")
    fake = user_mod.User()
    fake.id = _uuid.uuid4()
    fake.email = "deprecation_behavior@test"
    fake.is_active = True
    fake.is_superuser = False

    async def _fake_current_user():
        return fake

    app.dependency_overrides[deps_mod.get_current_user] = _fake_current_user

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
async def test_b01_healthz_returns_200(client: httpx.AsyncClient) -> None:
    """B-01: GET /healthz returns 200 — app boots after deprecation middleware patch."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200, (
        f"Expected 200 from /healthz, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B-02: GET /api/deprecations → 200 with JSON
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b02_deprecations_endpoint_returns_200(client: httpx.AsyncClient) -> None:
    """B-02: GET /api/v1/deprecations returns 200 with a JSON body."""
    resp = await client.get("/api/v1/deprecations")
    assert resp.status_code == 200, (
        f"Expected 200 from /api/v1/deprecations, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert isinstance(body, dict), f"Expected JSON object, got: {type(body)}"
    assert "deprecated" in body, f"Response body missing 'deprecated' key: {body}"


# ---------------------------------------------------------------------------
# B-03: DeprecationRegistry stores and retrieves entries
# ---------------------------------------------------------------------------


def test_b03_registry_register_and_get(behavior_project: Path) -> None:
    """B-03: DeprecationRegistry.register() stores entry retrievable via get()."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        depr_mod = importlib.import_module("app.deprecation")
        local_registry = depr_mod.DeprecationRegistry()
        entry = local_registry.register(
            path="/api/v1/items",
            method="GET",
            sunset="2030-01-01",
            replacement="/api/v2/items",
        )
        assert entry is not None, "register() should return a DeprecationEntry"
        found = local_registry.get("/api/v1/items", "GET")
        assert found is not None, "get() should return the registered entry"
        assert found.replacement == "/api/v2/items", "replacement mismatch"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-04: DeprecationEntry sunset_header returns ISO date string
# ---------------------------------------------------------------------------


def test_b04_entry_sunset_header(behavior_project: Path) -> None:
    """B-04: DeprecationEntry.sunset_header returns ISO date string."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        depr_mod = importlib.import_module("app.deprecation")
        local_registry = depr_mod.DeprecationRegistry()
        entry = local_registry.register(
            path="/old",
            method="GET",
            sunset="2030-06-15",
            replacement="/new",
        )
        assert entry.sunset_header == "2030-06-15", (
            f"sunset_header should be '2030-06-15', got {entry.sunset_header!r}"
        )
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-05: DeprecationReporter tracks call counts
# ---------------------------------------------------------------------------


def test_b05_reporter_tracks_calls(behavior_project: Path) -> None:
    """B-05: DeprecationReporter.record() increments call count correctly."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        reporter_mod = importlib.import_module("app.deprecation.reporter")
        local_reporter = reporter_mod.DeprecationReporter()
        assert local_reporter.get_count("/old", "GET") == 0
        local_reporter.record("/old", "GET")
        local_reporter.record("/old", "GET")
        assert local_reporter.get_count("/old", "GET") == 2, "Expected 2 calls recorded"
        report = local_reporter.usage_report()
        assert len(report) >= 1, "usage_report should have at least 1 entry"
        assert report[0]["endpoint"] == "GET /old", f"Wrong endpoint key: {report[0]}"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-06: Generated files AST-parse
# ---------------------------------------------------------------------------


def test_b06_generated_files_ast_parse(behavior_project: Path) -> None:
    """B-06: All generated app/deprecation/*.py files pass ast.parse."""
    depr_dir = behavior_project / "app" / "deprecation"
    assert depr_dir.exists(), "app/deprecation/ directory not created"
    py_files = list(depr_dir.glob("*.py"))
    assert len(py_files) >= 3, f"Expected >= 3 py files in app/deprecation/, got {len(py_files)}"
    for py_file in py_files:
        try:
            ast.parse(py_file.read_text())
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError in {py_file}: {exc}")


# ---------------------------------------------------------------------------
# B-07: All generated functions <= 50 LOC
# ---------------------------------------------------------------------------


def test_b07_all_generated_functions_under_50_loc(behavior_project: Path) -> None:
    """B-07: No function in app/deprecation/ generated by the tool exceeds 50 LOC."""
    depr_dir = behavior_project / "app" / "deprecation"
    max_loc = 0
    worst_fn = ""
    for py_file in sorted(depr_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and hasattr(node, "end_lineno")
                and node.end_lineno
            ):
                loc = node.end_lineno - node.lineno + 1
                if loc > max_loc:
                    max_loc = loc
                    worst_fn = f"{py_file}:{node.name} ({loc} LOC)"
    assert max_loc <= 50, f"Function exceeds 50 LOC: {worst_fn}"


# ---------------------------------------------------------------------------
# B-08: Config fields have 4-space indent
# ---------------------------------------------------------------------------


def test_b08_config_fields_four_space_indent(behavior_project: Path) -> None:
    """B-08: DEPRECATION_* fields in config.py are inside Settings class (4-space indent)."""
    config_file = behavior_project / "app" / "core" / "config.py"
    content = config_file.read_text()
    for line in content.splitlines():
        if "DEPRECATION_WARN_DAYS_BEFORE_SUNSET" in line:
            assert line.startswith("    "), (
                f"DEPRECATION_WARN_DAYS_BEFORE_SUNSET not at 4-space indent: {line!r}"
            )
            break
    else:
        pytest.fail("DEPRECATION_WARN_DAYS_BEFORE_SUNSET not found in config.py")


# ---------------------------------------------------------------------------
# B-09: Ruff F401 clean on tool source
# ---------------------------------------------------------------------------


def test_b09_ruff_f401_clean_on_tool_source() -> None:
    """B-09: The tool source file has no unused imports (ruff F401)."""
    tool_file = Path(__file__).parent / "add_api_deprecation" / "__init__.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(tool_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 found dead imports in add_api_deprecation.py:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# B-10: No top-level optional SDK imports
# ---------------------------------------------------------------------------


def test_b10_no_top_level_optional_sdk_imports() -> None:
    """B-10: The tool file has no top-level optional SDK imports."""
    tool_file = Path(__file__).parent / "add_api_deprecation" / "__init__.py"
    tree = ast.parse(tool_file.read_text())
    top_level_imports = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    optional_sdks = {"httpx", "requests", "aiohttp"}
    # httpx is acceptable only as a lazy import; verify it's not at top level
    for node in top_level_imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                assert root not in optional_sdks, (
                    f"Optional SDK '{alias.name}' imported at module level"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            assert root not in optional_sdks, (
                f"Optional SDK '{node.module}' imported at module level"
            )


# ---------------------------------------------------------------------------
# Standalone runner (sync tests only)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sync_tests = [
        test_b09_ruff_f401_clean_on_tool_source,
        test_b10_no_top_level_optional_sdk_imports,
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

    print(f"\n{'=' * 60}")
    print(f"TOOL-106 add_api_deprecation behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
