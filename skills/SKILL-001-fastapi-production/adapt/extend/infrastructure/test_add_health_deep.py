"""Tests for TOOL-061 add_health_deep.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_health_deep.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_health_deep.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_health_deep import add_health_deep
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _count_function_lines(source: str) -> list[tuple[str, int]]:
    """Return list of (function_name, line_count) for all functions in source."""
    tree = ast.parse(source)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno and node.lineno:
                results.append((node.name, node.end_lineno - node.lineno + 1))
    return results


# ---------------------------------------------------------------------------
# T-01: success
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="health_t01")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# T-02: idempotent — second run returns no_op
# ---------------------------------------------------------------------------

def test_idempotent_returns_no_op() -> None:
    """T-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="health_t02")
    r1 = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must not create files"
    assert not r2.files_modified, "Second run must not modify files"


# ---------------------------------------------------------------------------
# T-03: dry_run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing() -> None:
    """T-03: dry_run=True must return success but write no files."""
    project_dir = create_fixture_project(name="health_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_health_deep(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# T-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """T-04: Tool creates at least 9 new files (health package + route)."""
    project_dir = create_fixture_project(name="health_t04")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    # 8 health package files + 1 route = minimum 9
    assert len(result.files_created) >= 9, (
        f"Expected >= 9 files_created, got {len(result.files_created)}: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# T-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """T-05: Tool modifies at least 2 files (config.py, main.py, requirements.txt)."""
    project_dir = create_fixture_project(name="health_t05")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )


# ---------------------------------------------------------------------------
# T-06: all generated .py parse without SyntaxError
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """T-06: All .py files in the project parse without SyntaxError after tool run."""
    project_dir = create_fixture_project(name="health_t06")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# T-07: no function over 50 LOC in generated files
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """T-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="health_t07")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    health_dir = project_dir / "app" / "health"
    for py_file in sorted(health_dir.rglob("*.py")):
        source = py_file.read_text()
        for fn_name, loc in _count_function_lines(source):
            assert loc <= 50, (
                f"Function '{fn_name}' in {py_file} has {loc} LOC (max 50)"
            )


# ---------------------------------------------------------------------------
# T-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """T-08: app/core/config.py gains HEALTH_* settings fields."""
    project_dir = create_fixture_project(name="health_t08")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists(), "config.py must exist"
    content = config_file.read_text()
    assert "HEALTH_CHECK_TIMEOUT_MS" in content, "HEALTH_CHECK_TIMEOUT_MS not patched"
    assert "HEALTH_DISK_THRESHOLD_PCT" in content, "HEALTH_DISK_THRESHOLD_PCT not patched"
    assert "HEALTH_MEMORY_THRESHOLD_MB" in content, "HEALTH_MEMORY_THRESHOLD_MB not patched"


# ---------------------------------------------------------------------------
# T-09: requirements.txt patched with psutil
# ---------------------------------------------------------------------------

def test_requirements_patched() -> None:
    """T-09: requirements.txt gains psutil>=6.0.0."""
    project_dir = create_fixture_project(name="health_t09")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    req_file = project_dir / "requirements.txt"
    assert req_file.exists(), "requirements.txt must exist"
    content = req_file.read_text()
    assert "psutil" in content, "psutil must be added to requirements.txt"


# ---------------------------------------------------------------------------
# T-10: HealthRegistry created with correct interface
# ---------------------------------------------------------------------------

def test_health_registry_created() -> None:
    """T-10: app/health/registry.py contains HealthRegistry with required methods."""
    project_dir = create_fixture_project(name="health_t10")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    reg_file = project_dir / "app" / "health" / "registry.py"
    assert reg_file.exists(), "registry.py must be created"
    content = reg_file.read_text()
    assert "class HealthRegistry" in content, "HealthRegistry class not found"
    assert "register_check" in content, "register_check method not found"
    assert "run_all" in content, "run_all method not found"
    assert "run_readiness" in content, "run_readiness method not found"
    assert "run_liveness" in content, "run_liveness method not found"


# ---------------------------------------------------------------------------
# T-11: database check created
# ---------------------------------------------------------------------------

def test_db_check_created() -> None:
    """T-11: app/health/checks/database.py contains database_check function."""
    project_dir = create_fixture_project(name="health_t11")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    db_check = project_dir / "app" / "health" / "checks" / "database.py"
    assert db_check.exists(), "checks/database.py must be created"
    content = db_check.read_text()
    assert "async def database_check" in content, "database_check async function not found"
    assert "SELECT 1" in content or "select" in content.lower(), "DB connectivity check missing"


# ---------------------------------------------------------------------------
# T-12: redis check created
# ---------------------------------------------------------------------------

def test_redis_check_created() -> None:
    """T-12: app/health/checks/redis.py contains redis_check with memory stats."""
    project_dir = create_fixture_project(name="health_t12")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    redis_check = project_dir / "app" / "health" / "checks" / "redis.py"
    assert redis_check.exists(), "checks/redis.py must be created"
    content = redis_check.read_text()
    assert "async def redis_check" in content, "redis_check async function not found"
    assert "ping" in content, "Redis ping call not found"
    assert "memory" in content.lower(), "Redis memory stats not present"


# ---------------------------------------------------------------------------
# T-13: disk check created
# ---------------------------------------------------------------------------

def test_disk_check_created() -> None:
    """T-13: app/health/checks/disk.py uses psutil and threshold config."""
    project_dir = create_fixture_project(name="health_t13")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    disk_check = project_dir / "app" / "health" / "checks" / "disk.py"
    assert disk_check.exists(), "checks/disk.py must be created"
    content = disk_check.read_text()
    assert "async def disk_check" in content, "disk_check async function not found"
    assert "psutil" in content, "psutil import not present in disk check"
    assert "HEALTH_DISK_THRESHOLD_PCT" in content, "Disk threshold config not referenced"


# ---------------------------------------------------------------------------
# T-14: memory check created
# ---------------------------------------------------------------------------

def test_memory_check_created() -> None:
    """T-14: app/health/checks/memory.py uses psutil.Process for RSS."""
    project_dir = create_fixture_project(name="health_t14")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    mem_check = project_dir / "app" / "health" / "checks" / "memory.py"
    assert mem_check.exists(), "checks/memory.py must be created"
    content = mem_check.read_text()
    assert "async def memory_check" in content, "memory_check async function not found"
    assert "psutil" in content, "psutil import not present in memory check"
    assert "rss" in content.lower(), "RSS measurement not present"


# ---------------------------------------------------------------------------
# T-15: health models created
# ---------------------------------------------------------------------------

def test_health_models_created() -> None:
    """T-15: app/health/models.py defines HealthStatus, DependencyCheck, HealthReport."""
    project_dir = create_fixture_project(name="health_t15")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    models_file = project_dir / "app" / "health" / "models.py"
    assert models_file.exists(), "health/models.py must be created"
    content = models_file.read_text()
    assert "HealthStatus" in content, "HealthStatus not found in models.py"
    assert "DependencyCheck" in content, "DependencyCheck not found in models.py"
    assert "HealthReport" in content, "HealthReport not found in models.py"
    assert "latency_ms" in content, "latency_ms field not in DependencyCheck"


# ---------------------------------------------------------------------------
# T-16: deep route created with 3 endpoints
# ---------------------------------------------------------------------------

def test_deep_route_created() -> None:
    """T-16: app/api/routes/health_deep.py exposes /health/live, /ready, /deep."""
    project_dir = create_fixture_project(name="health_t16")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "health_deep.py"
    assert route_file.exists(), "health_deep.py route not created"
    content = route_file.read_text()
    assert "/live" in content, "/health/live endpoint missing"
    assert "/ready" in content, "/health/ready endpoint missing"
    assert "/deep" in content, "/health/deep endpoint missing"


# ---------------------------------------------------------------------------
# T-17: /health/ready runs critical checks only
# ---------------------------------------------------------------------------

def test_ready_route_runs_critical_only() -> None:
    """T-17: /health/ready calls run_readiness (critical checks only), not run_all."""
    project_dir = create_fixture_project(name="health_t17")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "health_deep.py"
    content = route_file.read_text()
    assert "run_readiness" in content, "readiness route must call run_readiness"
    # Verify run_all is NOT called in the readiness handler — parse and inspect
    tree = ast.parse(content)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "readiness":
            fn_src = ast.unparse(node)
            assert "run_all" not in fn_src, (
                "readiness handler must NOT call run_all — only critical checks"
            )


# ---------------------------------------------------------------------------
# T-18: timeout present in registry checks
# ---------------------------------------------------------------------------

def test_timeout_in_checks() -> None:
    """T-18: HealthRegistry uses asyncio.wait_for timeout on every check."""
    project_dir = create_fixture_project(name="health_t18")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    reg_file = project_dir / "app" / "health" / "registry.py"
    content = reg_file.read_text()
    assert "asyncio.wait_for" in content, "asyncio.wait_for timeout not found in registry"
    assert "timeout" in content, "timeout parameter not referenced in registry"


# ---------------------------------------------------------------------------
# T-19: health router registered in main.py
# ---------------------------------------------------------------------------

def test_routes_registered_in_main() -> None:
    """T-19: app/main.py is patched to import or reference health_deep router."""
    project_dir = create_fixture_project(name="health_t19")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    main_file = project_dir / "app" / "main.py"
    if main_file.exists():
        content = main_file.read_text()
        assert "health_deep" in content, "main.py must reference health_deep router"


# ---------------------------------------------------------------------------
# T-20: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """T-20: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="health_t20")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# T-21: next_steps present and mention psutil and .env
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """T-21: next_steps is non-empty and mentions psutil and env config."""
    project_dir = create_fixture_project(name="health_t21")
    result = add_health_deep(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) >= 3, "next_steps must have at least 3 items"
    combined = " ".join(result.next_steps).lower()
    assert "psutil" in combined, "next_steps should mention psutil"
    assert ".env" in combined or "env" in combined, "next_steps should mention env config"


# ---------------------------------------------------------------------------
# T-22: idempotent — project still parses after two runs
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """T-22: After two runs, all .py files remain parseable."""
    project_dir = create_fixture_project(name="health_t22")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# T-23: circuit breaker logic in registry
# ---------------------------------------------------------------------------

def test_circuit_breaker_in_registry() -> None:
    """T-23: HealthRegistry implements circuit-breaker degraded state on repeated failures."""
    project_dir = create_fixture_project(name="health_t23")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    reg_file = project_dir / "app" / "health" / "registry.py"
    content = reg_file.read_text()
    assert "degraded" in content.lower(), "Circuit-breaker degraded state not present"
    assert "failure" in content.lower() or "_failure_counts" in content, (
        "Failure counting for circuit breaker not present"
    )


# ---------------------------------------------------------------------------
# T-24: health __init__.py re-exports registry and models
# ---------------------------------------------------------------------------

def test_health_init_re_exports() -> None:
    """T-24: app/health/__init__.py re-exports HealthRegistry and models."""
    project_dir = create_fixture_project(name="health_t24")
    add_health_deep(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "health" / "__init__.py"
    assert init_file.exists(), "app/health/__init__.py must be created"
    content = init_file.read_text()
    assert "HealthRegistry" in content, "HealthRegistry not re-exported from __init__"
    assert "DependencyCheck" in content, "DependencyCheck not re-exported from __init__"
    assert "HealthReport" in content, "HealthReport not re-exported from __init__"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent_returns_no_op,
        test_dry_run_writes_nothing,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_requirements_patched,
        test_health_registry_created,
        test_db_check_created,
        test_redis_check_created,
        test_disk_check_created,
        test_memory_check_created,
        test_health_models_created,
        test_deep_route_created,
        test_ready_route_runs_critical_only,
        test_timeout_in_checks,
        test_routes_registered_in_main,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_circuit_breaker_in_registry,
        test_health_init_re_exports,
    ]

    passed = failed = 0
    for test_fn in tests:
        try:
            test_fn()
            print(f"  PASS  {test_fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {test_fn.__name__}: {exc}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"TOOL-061 add_health_deep: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
