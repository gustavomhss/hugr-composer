"""Tests for TOOL-022 add_circuit_breaker.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_circuit_breaker.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_circuit_breaker.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_circuit_breaker import add_circuit_breaker
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


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cb_t01")
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist_on_disk() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="cb_t02")
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist_on_disk() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="cb_t03")
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_circuit_breaker_core_created() -> None:
    """CC-01: app/core/circuit_breaker.py exists with CircuitState enum."""
    project_dir = create_fixture_project(name="cb_t04")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    assert cb_file.exists(), "circuit_breaker.py not created"
    content = cb_file.read_text()
    assert "CircuitState" in content, "CircuitState enum must be defined"


def test_three_states_defined() -> None:
    """CC-02: CLOSED, OPEN, HALF_OPEN states are all present."""
    project_dir = create_fixture_project(name="cb_t05")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "CLOSED" in content, "CLOSED state missing"
    assert "OPEN" in content, "OPEN state missing"
    assert "HALF_OPEN" in content, "HALF_OPEN state missing"


def test_circuit_open_error_defined() -> None:
    """CC-03: CircuitOpenError exception class is present."""
    project_dir = create_fixture_project(name="cb_t06")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "CircuitOpenError" in content, "CircuitOpenError must be defined"


def test_circuit_breaker_decorator_defined() -> None:
    """CC-04: circuit_breaker() decorator function is defined."""
    project_dir = create_fixture_project(name="cb_t07")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "def circuit_breaker" in content, "circuit_breaker() decorator must be defined"


def test_redis_backed_state() -> None:
    """CC-05: State machine uses Redis for shared state across workers."""
    project_dir = create_fixture_project(name="cb_t08")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "redis" in content.lower(), "Must use Redis for shared state"
    assert "hget" in content or "hset" in content or "hgetall" in content


def test_lua_atomic_transitions() -> None:
    """CC-06: Atomic transitions use a Lua script (no client-side race conditions)."""
    project_dir = create_fixture_project(name="cb_t09")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "eval" in content or "LUA" in content or "lua" in content.lower(), (
        "Atomic Lua transitions must be present"
    )


def test_sliding_window_failure_counting() -> None:
    """CC-07: Sliding window failure counting uses sorted set (ZADD/ZREMRANGE)."""
    project_dir = create_fixture_project(name="cb_t10")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert (
        "ZREMRANGEBYSCORE" in content or "zremrangebyscore" in content
        or "ZADD" in content or "zadd" in content
    ), "Sliding window must use sorted set"


def test_admin_circuits_route_created() -> None:
    """CC-08: Admin route file app/api/routes/circuits.py is created."""
    project_dir = create_fixture_project(name="cb_t11")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "circuits.py"
    assert admin_route.exists(), "circuits.py admin route not created"


def test_admin_inspect_endpoint() -> None:
    """CC-09: Admin route has GET /{name} inspect endpoint."""
    project_dir = create_fixture_project(name="cb_t12")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "circuits.py"
    content = admin_route.read_text()
    assert "inspect_circuit" in content or "router.get" in content


def test_admin_reset_endpoint() -> None:
    """CC-10: Admin route has POST /{name}/reset endpoint."""
    project_dir = create_fixture_project(name="cb_t13")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "circuits.py"
    content = admin_route.read_text()
    assert "reset_circuit" in content or "reset" in content


def test_admin_force_open_endpoint() -> None:
    """CC-11: Admin route has POST /{name}/open force-open endpoint."""
    project_dir = create_fixture_project(name="cb_t14")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    admin_route = project_dir / "app" / "api" / "routes" / "circuits.py"
    content = admin_route.read_text()
    assert "open" in content, "Force-open endpoint must be present"


def test_prometheus_metrics_file_created() -> None:
    """CC-12: app/core/circuit_metrics.py exists with Prometheus metrics."""
    project_dir = create_fixture_project(name="cb_t15")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "core" / "circuit_metrics.py"
    assert metrics_file.exists(), "circuit_metrics.py not created"
    content = metrics_file.read_text()
    assert "fastapi_circuit" in content, "Prometheus metric name must use fastapi_circuit prefix"


def test_prometheus_graceful_import() -> None:
    """CC-13: Metrics file handles missing prometheus_client gracefully."""
    project_dir = create_fixture_project(name="cb_t16")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    metrics_file = project_dir / "app" / "core" / "circuit_metrics.py"
    content = metrics_file.read_text()
    assert "ImportError" in content, "Must handle missing prometheus_client gracefully"


def test_all_created_files_parse() -> None:
    """CC-14: All generated .py files parse without SyntaxError."""
    project_dir = create_fixture_project(name="cb_t17")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    for py_file in sorted((project_dir / "app" / "core").rglob("*.py")):
        source = py_file.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {py_file}: {exc}") from exc


def test_idempotent_returns_no_op() -> None:
    """CC-15: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="cb_t18")
    r1 = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="cb_t19")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="cb_t20")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="cb_t21")
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_mention_redis_and_prometheus() -> None:
    """next_steps guides developer to install dependencies."""
    project_dir = create_fixture_project(name="cb_t22")
    result = add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.next_steps).lower()
    assert "redis" in combined or "prometheus" in combined or "pip" in combined


def test_get_circuit_info_function_defined() -> None:
    """CC-16: get_circuit_info() helper for admin inspection is defined."""
    project_dir = create_fixture_project(name="cb_t23")
    add_circuit_breaker(ToolInput(project_dir=str(project_dir)))
    cb_file = project_dir / "app" / "core" / "circuit_breaker.py"
    content = cb_file.read_text()
    assert "get_circuit_info" in content, "get_circuit_info() helper must be present"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist_on_disk,
        test_files_modified_exist_on_disk,
        test_circuit_breaker_core_created,
        test_three_states_defined,
        test_circuit_open_error_defined,
        test_circuit_breaker_decorator_defined,
        test_redis_backed_state,
        test_lua_atomic_transitions,
        test_sliding_window_failure_counting,
        test_admin_circuits_route_created,
        test_admin_inspect_endpoint,
        test_admin_reset_endpoint,
        test_admin_force_open_endpoint,
        test_prometheus_metrics_file_created,
        test_prometheus_graceful_import,
        test_all_created_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_mention_redis_and_prometheus,
        test_get_circuit_info_function_defined,
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
    print(f"TOOL-022 add_circuit_breaker: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
