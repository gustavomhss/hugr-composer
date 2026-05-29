"""Behavior tests for TOOL-092 add_docker_production.

Proves that:
1. The app still boots cleanly after the tool patches config.py.
2. GET /healthz returns 200 after patching.
3. Generated Python files have no lazy-import violations.
4. All generated functions remain <= 50 LOC.
5. Config fields have correct 4-space indent.
6. No ruff F401 dead imports in the generated tool source.

Patches applied (so tests run without Docker):
- app/core/db.py            → SQLite + aiosqlite (no Postgres)
- app/middleware/idempotency.py → pass-through stub (no Redis)
- REDIS_URL env var          → removed

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_docker_production_behavior.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_docker_production_behavior.py
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
from adapt.extend.infrastructure.add_docker_production import add_docker_production
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Shared fixture — one project, all tests reuse it
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
    """Generate a fixture project with add_docker_production applied.

    Returns:
        Project root with SQLite patch, idempotency stub, and tool applied.
    """
    tmp = tmp_path_factory.mktemp("docker_behavior")
    project_dir = create_fixture_project(name="docker_behavior", tmp_dir=tmp)

    result = add_docker_production(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_docker_production failed in fixture setup: {result.error}"
    )

    # Patch 1: SQLite db.py
    db_file = project_dir / "app" / "core" / "db.py"
    db_file.write_text(_SQLITE_DB_PY)

    # Patch 2: idempotency stub
    idempotency_file = project_dir / "app" / "middleware" / "idempotency.py"
    if idempotency_file.exists():
        idempotency_file.write_text(_IDEMPOTENCY_STUB_PY)

    # Remove REDIS_URL so no Redis dependency at boot
    os.environ.pop("REDIS_URL", None)

    return project_dir


@pytest.fixture(scope="module")
def booted_app(behavior_project: Path):
    """Import the ASGI app from the behavior_project.

    Returns:
        The FastAPI app instance, ready for httpx.ASGITransport.
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
    """GET /healthz returns 200 — proves app boots after config patch."""
    resp = await client.get("/healthz")
    assert resp.status_code == 200, (
        f"Expected 200 from /healthz after docker production patch, "
        f"got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# B-02: App boots with DOCKER_* config fields
# ---------------------------------------------------------------------------


def test_docker_config_fields_importable(behavior_project: Path) -> None:
    """app/core/config.py with DOCKER_* fields imports without error."""
    project_str = str(behavior_project)
    if project_str not in sys.path:
        sys.path.insert(0, project_str)
    _clear_modules()
    try:
        config_mod = importlib.import_module("app.core.config")
        settings = config_mod.settings
        assert hasattr(settings, "DOCKER_WORKERS"), "settings missing DOCKER_WORKERS"
        assert hasattr(settings, "DOCKER_PORT"), "settings missing DOCKER_PORT"
        assert hasattr(settings, "DOCKER_HEALTH_PATH"), "settings missing DOCKER_HEALTH_PATH"
    finally:
        _clear_modules()


# ---------------------------------------------------------------------------
# B-03: No lazy-import violations in tool source
# ---------------------------------------------------------------------------


def test_no_top_level_optional_sdk_imports(behavior_project: Path) -> None:
    """The tool file has no top-level optional SDK imports.

    All SDKs not in stdlib/fastapi must be inside function bodies.
    """
    tool_file = Path(__file__).parent / "add_docker_production" / "__init__.py"
    tree = ast.parse(tool_file.read_text())
    top_level_imports = [
        node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    optional_sdks = {"docker", "boto3", "kubernetes"}
    for node in top_level_imports:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in optional_sdks, (
                    f"Optional SDK '{alias.name}' imported at module level — must be lazy"
                )
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in optional_sdks, (
                f"Optional SDK '{node.module}' imported at module level — must be lazy"
            )


# ---------------------------------------------------------------------------
# B-04: All generated functions <= 50 LOC
# ---------------------------------------------------------------------------


def test_all_generated_functions_under_50_loc(behavior_project: Path) -> None:
    """No function in the app/ directory generated by the tool exceeds 50 LOC."""
    app_dir = behavior_project / "app"
    max_loc = 0
    worst_fn = ""
    for py_file in sorted(app_dir.rglob("*.py")):
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
# B-05: Config fields have 4-space indent
# ---------------------------------------------------------------------------


def test_config_fields_four_space_indent(behavior_project: Path) -> None:
    """DOCKER_* fields in config.py are inside Settings class (4-space indent)."""
    config_file = behavior_project / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("DOCKER_WORKERS", "DOCKER_PORT", "DOCKER_HEALTH_PATH"):
        for line in content.splitlines():
            if field in line:
                assert line.startswith("    "), f"{field} not at 4-space indent: {line!r}"
                break
        else:
            pytest.fail(f"{field} not found in config.py at all")


# ---------------------------------------------------------------------------
# B-06: Ruff F401 clean on tool source
# ---------------------------------------------------------------------------


def test_ruff_f401_clean_on_tool_source() -> None:
    """The tool source file has no unused imports (ruff F401)."""
    tool_file = Path(__file__).parent / "add_docker_production" / "__init__.py"
    result = subprocess.run(
        ["python3", "-m", "ruff", "check", "--select=F401", str(tool_file)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"ruff F401 found dead imports in add_docker_production.py:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# B-07: Dockerfile contains all required directives
# ---------------------------------------------------------------------------


def test_dockerfile_has_required_directives(behavior_project: Path) -> None:
    """Dockerfile contains HEALTHCHECK, USER, FROM builder, FROM runtime."""
    dockerfile = behavior_project / "Dockerfile"
    content = dockerfile.read_text()
    for directive in ("HEALTHCHECK", "USER 1000", "builder", "runtime"):
        assert directive in content, f"Dockerfile missing '{directive}' directive"


# ---------------------------------------------------------------------------
# B-08: docker-compose.prod.yml is valid YAML-like structure
# ---------------------------------------------------------------------------


def test_compose_prod_has_services(behavior_project: Path) -> None:
    """docker-compose.prod.yml contains 'services:' and 'volumes:' keys."""
    compose = behavior_project / "docker-compose.prod.yml"
    content = compose.read_text()
    assert "services:" in content, "docker-compose.prod.yml missing 'services:' key"
    assert "volumes:" in content, "docker-compose.prod.yml missing 'volumes:' key"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import anyio

    async def _run_async_tests() -> list[tuple[str, bool, str]]:
        """Run the async tests and return (name, passed, error) tuples."""
        results = []
        project_dir = create_fixture_project(name="docker_beh_standalone")
        add_docker_production(ToolInput(project_dir=str(project_dir)))

        db_file = project_dir / "app" / "core" / "db.py"
        db_file.write_text(_SQLITE_DB_PY)
        idempotency_file = project_dir / "app" / "middleware" / "idempotency.py"
        if idempotency_file.exists():
            idempotency_file.write_text(_IDEMPOTENCY_STUB_PY)
        os.environ.pop("REDIS_URL", None)

        project_str = str(project_dir)
        sys.path.insert(0, project_str)
        app_module = importlib.import_module("app.main")
        app = app_module.app

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            for name, coro in [
                ("test_healthz_returns_200", test_healthz_returns_200(client)),
            ]:
                try:
                    await coro
                    results.append((name, True, ""))
                except Exception as exc:
                    results.append((name, False, str(exc)))
        return results

    sync_tests = [
        test_no_top_level_optional_sdk_imports,
        test_ruff_f401_clean_on_tool_source,
        test_dockerfile_has_required_directives,
    ]

    passed = failed = 0
    async_results = anyio.from_thread.run_sync(lambda: anyio.run(_run_async_tests))
    for name, ok, err in async_results:
        if ok:
            print(f"  PASS  {name}")
            passed += 1
        else:
            print(f"  FAIL  {name}: {err}")
            failed += 1

    for test_fn in sync_tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"TOOL-092 behavior: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
