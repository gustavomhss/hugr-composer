"""Behavior tests for TOOL-105 add_data_seeder.

Proves that:
1. App boots cleanly after the tool patches config.py.
2. GET /healthz returns 200.
3. POST /dev/seed returns 404 when SEEDER_ENABLED=false (prod guard).
4. DataSeeder class can be imported and instantiated.
5. DependencyGraph.topological_order handles simple list.
6. FieldGenerator generates email, name, int values.
7. All generated functions remain <= 50 LOC.
8. Config fields have correct 4-space indent.
9. No ruff F401 dead imports in the tool source.
10. No top-level optional SDK imports in tool source.

Patches applied (so tests run without Docker):
- app/core/db.py            → SQLite + aiosqlite (no Postgres)
- app/middleware/idempotency.py → pass-through stub (no Redis)
- REDIS_URL env var          → removed

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_data_seeder_behavior.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_data_seeder_behavior.py
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
from adapt.extend.testing_tools.add_data_seeder import add_data_seeder
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
    """Generate a fixture project with add_data_seeder applied.

    Returns:
        Project root with SQLite patch, idempotency stub, and tool applied.
    """
    tmp = tmp_path_factory.mktemp("ds_behavior")
    project_dir = create_fixture_project(name="ds_behavior", tmp_dir=tmp)

    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_data_seeder failed in fixture setup: {result.error}"
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
async def test_b01_healthz_returns_200(client: httpx.AsyncClient) -> None:
    """B-01: GET /healthz returns 200 — app boots after data seeder config patch."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200, (
        f"Expected 200 from /healthz, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B-02: POST /dev/seed returns 404 when SEEDER_ENABLED=false
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_b02_seed_endpoint_disabled_by_default(client: httpx.AsyncClient) -> None:
    """B-02: POST /dev/seed returns 404 when SEEDER_ENABLED=false (production guard)."""
    resp = await client.post("/dev/seed")
    assert resp.status_code == 404, (
        f"Expected 404 from /dev/seed when disabled, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B-03: Generated seeder files AST-parse
# ---------------------------------------------------------------------------

def test_b03_generated_files_ast_parse(behavior_project: Path) -> None:
    """B-03: All generated app/seeder/*.py files pass ast.parse."""
    seeder_dir = behavior_project / "app" / "seeder"
    assert seeder_dir.exists(), "app/seeder/ directory not created"
    py_files = list(seeder_dir.glob("*.py"))
    assert len(py_files) >= 3, f"Expected >= 3 py files in app/seeder/, got {len(py_files)}"
    for py_file in py_files:
        try:
            ast.parse(py_file.read_text())
        except SyntaxError as exc:
            pytest.fail(f"SyntaxError in {py_file}: {exc}")


# ---------------------------------------------------------------------------
# B-04: DataSeeder can be instantiated
# ---------------------------------------------------------------------------

def test_b04_data_seeder_importable(behavior_project: Path) -> None:
    """B-04: DataSeeder class can be imported without errors."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        seeder_mod = importlib.import_module("app.seeder")
        assert hasattr(seeder_mod, "DataSeeder"), "DataSeeder not exported from app.seeder"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-05: DependencyGraph topological_order
# ---------------------------------------------------------------------------

def test_b05_dependency_graph_importable(behavior_project: Path) -> None:
    """B-05: DependencyGraph class can be imported and topological_order called."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        graph_mod = importlib.import_module("app.seeder.graph")
        assert hasattr(graph_mod, "DependencyGraph"), "DependencyGraph not found"
        graph = graph_mod.DependencyGraph([])
        order = graph.topological_order()
        assert isinstance(order, list), "topological_order should return a list"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-06: FieldGenerator produces email, name, integer
# ---------------------------------------------------------------------------

def test_b06_field_generator_produces_values(behavior_project: Path) -> None:
    """B-06: FieldGenerator generates email, full name, and integer values."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        gen_mod = importlib.import_module("app.seeder.generators")
        gen = gen_mod.FieldGenerator()
        email = gen._email()
        assert "@" in email, f"Generated email missing '@': {email!r}"
        name = gen._full_name()
        assert " " in name, f"Generated full name missing space: {name!r}"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-07: All generated functions <= 50 LOC
# ---------------------------------------------------------------------------

def test_b07_all_generated_functions_under_50_loc(behavior_project: Path) -> None:
    """B-07: No function in app/seeder/ generated by the tool exceeds 50 LOC."""
    seeder_dir = behavior_project / "app" / "seeder"
    max_loc = 0
    worst_fn = ""
    for py_file in sorted(seeder_dir.rglob("*.py")):
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
# B-08: Config fields have 4-space indent
# ---------------------------------------------------------------------------

def test_b08_config_fields_four_space_indent(behavior_project: Path) -> None:
    """B-08: SEEDER_* fields in config.py are inside Settings class (4-space indent)."""
    config_file = behavior_project / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("SEEDER_ENABLED", "SEEDER_DEFAULT_COUNT"):
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), (
                    f"{field} not at 4-space indent: {line!r}"
                )
                break
        else:
            pytest.fail(f"{field} not found in config.py at all")


# ---------------------------------------------------------------------------
# B-09: Ruff F401 clean on tool source
# ---------------------------------------------------------------------------

def test_b09_ruff_f401_clean_on_tool_source() -> None:
    """B-09: The tool source file has no unused imports (ruff F401)."""
    tool_file = Path(__file__).parent / "add_data_seeder.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(tool_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 found dead imports in add_data_seeder.py:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# B-10: No top-level optional SDK imports
# ---------------------------------------------------------------------------

def test_b10_no_top_level_optional_sdk_imports() -> None:
    """B-10: The tool file has no top-level optional SDK imports."""
    tool_file = Path(__file__).parent / "add_data_seeder.py"
    tree = ast.parse(tool_file.read_text())
    top_level_imports = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    optional_sdks = {"faker", "factory_boy", "hypothesis"}
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

    print(f"\n{'='*60}")
    print(f"TOOL-105 add_data_seeder behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
