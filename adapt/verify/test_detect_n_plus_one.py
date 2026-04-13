"""Tests for TOOL-028 detect_n_plus_one.

Verifies all completeness criteria: idempotency, file creation, middleware
content, decorator content, ContextVar listener, CI workflow, and dry_run mode.

Run with::

    PYTHONPATH=. python3 adapt/verify/test_detect_n_plus_one.py
"""

from __future__ import annotations

import ast
import sys
import tempfile
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.verify.detect_n_plus_one import detect_n_plus_one
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ok(path: Path) -> bool:
    try:
        ast.parse(path.read_text())
        return True
    except SyntaxError:
        return False


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project = create_fixture_project(name="n1_t01")
    result = detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert result.status == "success", result.error


def test_no_op_on_second_run() -> None:
    """T-02: Second run returns status='no_op' (idempotency)."""
    project = create_fixture_project(name="n1_t02")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    result = detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert result.status == "no_op"


def test_middleware_file_created() -> None:
    """T-03: app/api/middleware/query_counter.py is created."""
    project = create_fixture_project(name="n1_t03")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    mw = project / "app" / "api" / "middleware" / "query_counter.py"
    assert mw.exists()


def test_middleware_contains_class() -> None:
    """T-04: Middleware file contains QueryCounterMiddleware class."""
    project = create_fixture_project(name="n1_t04")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "app" / "api" / "middleware" / "query_counter.py").read_text()
    assert "QueryCounterMiddleware" in content
    assert "BaseHTTPMiddleware" in content


def test_middleware_parses() -> None:
    """T-05: Middleware file has no syntax errors."""
    project = create_fixture_project(name="n1_t05")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "app" / "api" / "middleware" / "query_counter.py")


def test_query_listener_created() -> None:
    """T-06: app/core/query_listener.py is created."""
    project = create_fixture_project(name="n1_t06")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert (project / "app" / "core" / "query_listener.py").exists()


def test_query_listener_has_contextvar() -> None:
    """T-07: query_listener.py imports and uses ContextVar."""
    project = create_fixture_project(name="n1_t07")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "app" / "core" / "query_listener.py").read_text()
    assert "ContextVar" in content
    assert "query_count" in content


def test_query_listener_parses() -> None:
    """T-08: query_listener.py has no syntax errors."""
    project = create_fixture_project(name="n1_t08")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "app" / "core" / "query_listener.py")


def test_decorator_file_created() -> None:
    """T-09: app/core/nplusone.py decorator file is created."""
    project = create_fixture_project(name="n1_t09")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert (project / "app" / "core" / "nplusone.py").exists()


def test_decorator_has_max_queries() -> None:
    """T-10: nplusone.py contains the @max_queries decorator."""
    project = create_fixture_project(name="n1_t10")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "app" / "core" / "nplusone.py").read_text()
    assert "max_queries" in content
    assert "def decorator" in content


def test_decorator_parses() -> None:
    """T-11: nplusone.py has no syntax errors."""
    project = create_fixture_project(name="n1_t11")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "app" / "core" / "nplusone.py")


def test_budgets_file_created() -> None:
    """T-12: .nplusone-budgets.yaml is created."""
    project = create_fixture_project(name="n1_t12")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert (project / ".nplusone-budgets.yaml").exists()


def test_budgets_has_global_threshold() -> None:
    """T-13: .nplusone-budgets.yaml contains global_threshold field."""
    project = create_fixture_project(name="n1_t13")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / ".nplusone-budgets.yaml").read_text()
    assert "global_threshold" in content


def test_conftest_created() -> None:
    """T-14: tests/conftest_nplusone.py is created."""
    project = create_fixture_project(name="n1_t14")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert (project / "tests" / "conftest_nplusone.py").exists()


def test_conftest_has_autouse_fixture() -> None:
    """T-15: conftest_nplusone.py contains autouse reset fixture."""
    project = create_fixture_project(name="n1_t15")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "tests" / "conftest_nplusone.py").read_text()
    assert "autouse=True" in content
    assert "reset_counters" in content


def test_conftest_parses() -> None:
    """T-16: conftest_nplusone.py has no syntax errors."""
    project = create_fixture_project(name="n1_t16")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert _parse_ok(project / "tests" / "conftest_nplusone.py")


def test_ci_workflow_created() -> None:
    """T-17: .github/workflows/nplusone.yml is created."""
    project = create_fixture_project(name="n1_t17")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert (project / ".github" / "workflows" / "nplusone.yml").exists()


def test_ci_workflow_has_nplusone_env() -> None:
    """T-18: CI workflow sets NPLUSONE_ENABLED=1."""
    project = create_fixture_project(name="n1_t18")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / ".github" / "workflows" / "nplusone.yml").read_text()
    assert "NPLUSONE_ENABLED" in content


def test_dry_run_no_files_written() -> None:
    """T-19: dry_run=True returns success but writes no files."""
    project = create_fixture_project(name="n1_t19")
    result = detect_n_plus_one(ToolInput(project_dir=str(project), dry_run=True))
    assert result.status == "success"
    assert not (project / "app" / "api" / "middleware" / "query_counter.py").exists()


def test_files_created_all_exist() -> None:
    """T-20: Every path in files_created actually exists on disk."""
    project = create_fixture_project(name="n1_t20")
    result = detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Missing: {path_str}"


def test_execution_time_recorded() -> None:
    """T-21: execution_time_ms is a non-negative integer."""
    project = create_fixture_project(name="n1_t21")
    result = detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert isinstance(result.execution_time_ms, int)
    assert result.execution_time_ms >= 0


def test_next_steps_non_empty() -> None:
    """T-22: next_steps contains at least one actionable item."""
    project = create_fixture_project(name="n1_t22")
    result = detect_n_plus_one(ToolInput(project_dir=str(project)))
    assert result.next_steps


def test_nplusone_exception_class_defined() -> None:
    """T-23: NPlusOneDetected exception class is defined in middleware."""
    project = create_fixture_project(name="n1_t23")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "app" / "api" / "middleware" / "query_counter.py").read_text()
    assert "class NPlusOneDetected" in content


def test_reset_counters_function_defined() -> None:
    """T-24: reset_counters() function is defined in query_listener.py."""
    project = create_fixture_project(name="n1_t24")
    detect_n_plus_one(ToolInput(project_dir=str(project)))
    content = (project / "app" / "core" / "query_listener.py").read_text()
    assert "def reset_counters" in content


# ---------------------------------------------------------------------------
# Self-runner (no pytest required)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {fn.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
