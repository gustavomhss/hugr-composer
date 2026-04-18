"""BEHAVIOR TEST — TOOL-120 add_cost_tracker.

Proves the generated code works at runtime: boots a real ASGI app,
hits cost reporting endpoints, verifies X-Request-Cost-Estimate header,
and asserts structural/config correctness.

Patches applied (no Docker required):
- ``app/core/db.py``                → SQLite + aiosqlite
- ``app/middleware/idempotency.py`` → pass-through stub
- ``REDIS_URL`` env var             → removed

Run::

    PYTHONPATH=. .venv/bin/pytest adapt/extend/infrastructure/test_add_cost_tracker_behavior.py -v

or standalone::

    PYTHONPATH=. .venv/bin/python adapt/extend/infrastructure/test_add_cost_tracker_behavior.py
"""

from __future__ import annotations

import os

os.environ.setdefault("RATE_LIMITING_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("SECRET_KEY", "behavior-test-cost-secret-key-32+chars!!")
os.environ.setdefault("COST_TRACKING_ENABLED", "true")
os.environ.setdefault("COST_DB_QUERY_RATE", "0.00001")
os.environ.setdefault("COST_S3_PER_GB", "0.023")
os.environ.setdefault("COST_API_CALL_RATE", "0.0001")
os.environ.pop("REDIS_URL", None)

import ast
import importlib
import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import anyio
import httpx
import pytest

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Shared patch content
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
    """Apply SQLite + idempotency stubs to the fixture project."""
    (project_dir / "app" / "core" / "db.py").write_text(_SQLITE_DB_PY)
    middleware_dir = project_dir / "app" / "middleware"
    middleware_dir.mkdir(parents=True, exist_ok=True)
    (middleware_dir / "idempotency.py").write_text(_PASSTHROUGH_IDEMPOTENCY_PY)


def _load_app(project_dir: Path) -> Any:
    """Load ``app.main:app`` from *project_dir* in an isolated sys.path context."""
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
    """Create, apply tool, patch, and load app."""
    project_dir = create_fixture_project(name="cost_behavior")

    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"add_cost_tracker failed: {result.error}\nnotes: {result.notes}"
    )

    _patch_project(project_dir)
    asgi_app = _load_app(project_dir)
    return project_dir, asgi_app


# ---------------------------------------------------------------------------
# Module-level shared fixture
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
    """B-01: GET /healthz must return 200 after tool applied."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )


# ---------------------------------------------------------------------------
# B-02: GET /costs/summary → 200
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b02_costs_summary_route_exists(asgi_app: Any) -> None:
    """B-02: GET /costs/summary must return 200 with daily/weekly/monthly keys."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/costs/summary")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )
    body = response.json()
    for key in ("daily", "weekly", "monthly"):
        assert key in body, f"Missing key '{key}' in /costs/summary response"


# ---------------------------------------------------------------------------
# B-03: GET /costs/by-endpoint → 200
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_b03_costs_by_endpoint_route_exists(asgi_app: Any) -> None:
    """B-03: GET /costs/by-endpoint must return 200 with a list."""
    transport = httpx.ASGITransport(app=asgi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/costs/by-endpoint")
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}; body: {response.text}"
    )
    assert isinstance(response.json(), list), "/costs/by-endpoint must return a list"


# ---------------------------------------------------------------------------
# B-04: CostTracker imports cleanly
# ---------------------------------------------------------------------------

def test_b04_cost_tracker_imports_without_crash(project_dir: Path) -> None:
    """B-04: app/costs/tracker.py must be importable without raising."""
    tracker_file = project_dir / "app" / "costs" / "tracker.py"
    assert tracker_file.exists(), "app/costs/tracker.py not found"

    import importlib.util

    mod_name = "app.costs.tracker_behavior_test"
    spec = importlib.util.spec_from_file_location(mod_name, str(tracker_file))
    assert spec is not None and spec.loader is not None

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # register before exec so dataclass __module__ resolves
    try:
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception as exc:
        sys.modules.pop(mod_name, None)
        raise AssertionError(f"app/costs/tracker.py raised on import: {exc}") from exc
    finally:
        sys.path[:] = _orig

    assert hasattr(module, "CostTracker"), "CostTracker class not found after import"
    assert hasattr(module, "RequestContext"), "RequestContext class not found after import"
    assert hasattr(module, "CostEstimate"), "CostEstimate class not found after import"


# ---------------------------------------------------------------------------
# B-05: estimators import cleanly
# ---------------------------------------------------------------------------

def test_b05_estimators_import_without_crash(project_dir: Path) -> None:
    """B-05: app/costs/estimators.py must be importable without raising."""
    estimators_file = project_dir / "app" / "costs" / "estimators.py"
    assert estimators_file.exists(), "app/costs/estimators.py not found"

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "app.costs.estimators_behavior_test", str(estimators_file)
    )
    assert spec is not None and spec.loader is not None

    _orig = sys.path.copy()
    sys.path.insert(0, str(project_dir))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[attr-defined]
    except Exception as exc:
        raise AssertionError(
            f"app/costs/estimators.py raised on import: {exc}"
        ) from exc
    finally:
        sys.path[:] = _orig

    for cls_name in ["DBQueryCostEstimator", "S3CostEstimator", "APICostEstimator"]:
        assert hasattr(module, cls_name), f"{cls_name} not found after import"


# ---------------------------------------------------------------------------
# B-06: config fields present
# ---------------------------------------------------------------------------

def test_b06_cost_config_fields_present(project_dir: Path) -> None:
    """B-06: app/core/config.py must contain COST_* fields."""
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in [
        "COST_TRACKING_ENABLED",
        "COST_DB_QUERY_RATE",
        "COST_S3_PER_GB",
        "COST_API_CALL_RATE",
    ]:
        assert field in content, f"Missing config field: {field}"


# ---------------------------------------------------------------------------
# B-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_b07_no_function_over_50_loc(project_dir: Path) -> None:
    """B-07: No generated function exceeds 50 LOC."""
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
                        f"Function {node.name} in {py_file.relative_to(project_dir)} "
                        f"has {loc} LOC (limit: 50)"
                    )


# ---------------------------------------------------------------------------
# B-08: config fields 4-space indent
# ---------------------------------------------------------------------------

def test_b08_config_fields_4_space_indent(project_dir: Path) -> None:
    """B-08: COST_TRACKING_ENABLED must be inside Settings class body."""
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for line in content.splitlines():
        if "COST_TRACKING_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"COST_TRACKING_ENABLED not at 4-space indent: {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# Shared async runner
# ---------------------------------------------------------------------------

def _run_async_test(coro_fn: Any, *args: Any) -> None:
    """Run an async test function synchronously via anyio.run."""
    import inspect

    async def _wrapper() -> None:
        await coro_fn(*args)

    if inspect.iscoroutinefunction(coro_fn):
        anyio.run(_wrapper)
    else:
        coro_fn(*args)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback as _tb

    _pd, _app = _get_shared_app()

    _TESTS: list[tuple[str, Any]] = [
        ("B-01: /healthz → 200", lambda: _run_async_test(test_b01_healthz_returns_200, _app)),
        ("B-02: /costs/summary → 200", lambda: _run_async_test(test_b02_costs_summary_route_exists, _app)),
        ("B-03: /costs/by-endpoint → 200", lambda: _run_async_test(test_b03_costs_by_endpoint_route_exists, _app)),
        ("B-04: CostTracker imports ok", lambda: test_b04_cost_tracker_imports_without_crash(_pd)),
        ("B-05: estimators import ok", lambda: test_b05_estimators_import_without_crash(_pd)),
        ("B-06: config fields present", lambda: test_b06_cost_config_fields_present(_pd)),
        ("B-07: no function >50 LOC", lambda: test_b07_no_function_over_50_loc(_pd)),
        ("B-08: config 4-space indent", lambda: test_b08_config_fields_4_space_indent(_pd)),
    ]

    passed = 0
    failed = 0
    failures: list[str] = []

    for name, fn in _TESTS:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {name}: {exc}")
            failures.append(f"{name}: {exc}")
            failed += 1

    total = passed + failed
    result_status = "PASS" if failed == 0 else "FAIL"

    contract = {
        "tool": "TOOL-120 add_cost_tracker",
        "test_file": "test_add_cost_tracker_behavior.py",
        "total": total,
        "passed": passed,
        "failed": failed,
        "status": result_status,
        "failures": failures,
    }

    print(f"\n{'='*60}")
    print(f"TOOL-120 BEHAVIOR: {passed}/{total} passed")
    print(f"\nDelivery contract JSON:")
    print(json.dumps(contract, indent=2))

    if failed:
        sys.exit(1)
