"""Structural tests for TOOL-098 add_retry_budget.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_retry_budget.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_retry_budget.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_retry_budget import add_retry_budget
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="rb_t01")
    result = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on second run."""
    project_dir = create_fixture_project(name="rb_t02")
    r1 = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="rb_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_retry_budget(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 3 files created and all exist on disk."""
    project_dir = create_fixture_project(name="rb_t04")
    result = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = create_fixture_project(name="rb_t05")
    result = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 file modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="rb_t06")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="rb_t07")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    resilience_dir = project_dir / "app" / "resilience"
    violations: list[str] = []
    for py_file in sorted(resilience_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file.name}:{node.name} ({loc} LOC)")
    assert not violations, "Functions > 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: RETRY_BUDGET_* fields appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="rb_t08")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "RETRY_BUDGET_RATIO" in content, "RETRY_BUDGET_RATIO missing from config"
    assert "RETRY_BUDGET_WINDOW_S" in content, "RETRY_BUDGET_WINDOW_S missing from config"
    assert "RETRY_BUDGET_MIN_REQUESTS" in content, "RETRY_BUDGET_MIN_REQUESTS missing from config"
    for line in content.splitlines():
        if "RETRY_BUDGET_" in line and ":" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-10: route registered in routes file
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: retry_status.py router exists in app/api/routes/."""
    project_dir = create_fixture_project(name="rb_t10")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "retry_status.py"
    assert route_file.exists(), "retry_status.py not created"
    content = route_file.read_text()
    assert "router" in content, "router not defined in retry_status.py"
    assert "retry-budget" in content or "retry_budget" in content


# ---------------------------------------------------------------------------
# CC-11: RetryBudget class defined
# ---------------------------------------------------------------------------

def test_retry_budget_class_defined() -> None:
    """CC-11: RetryBudget class is defined in retry_budget.py."""
    project_dir = create_fixture_project(name="rb_t11")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    assert budget_file.exists(), "retry_budget.py not created"
    content = budget_file.read_text()
    assert "class RetryBudget" in content, "RetryBudget class must be defined"


# ---------------------------------------------------------------------------
# CC-12: BudgetExhaustedError defined
# ---------------------------------------------------------------------------

def test_budget_exhausted_error_defined() -> None:
    """CC-12: BudgetExhaustedError exception class is defined."""
    project_dir = create_fixture_project(name="rb_t12")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "BudgetExhaustedError" in content, "BudgetExhaustedError must be defined"


# ---------------------------------------------------------------------------
# CC-13: sliding window present
# ---------------------------------------------------------------------------

def test_sliding_window_present() -> None:
    """CC-13: Sliding window logic is present (evict/deque pattern)."""
    project_dir = create_fixture_project(name="rb_t13")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "deque" in content, "Must use deque for sliding window"
    assert "evict" in content or "popleft" in content, "Must evict expired entries"


# ---------------------------------------------------------------------------
# CC-14: decorator defined
# ---------------------------------------------------------------------------

def test_with_retry_budget_decorator_defined() -> None:
    """CC-14: with_retry_budget decorator is defined in retry_decorator.py."""
    project_dir = create_fixture_project(name="rb_t14")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    decorator_file = project_dir / "app" / "resilience" / "retry_decorator.py"
    assert decorator_file.exists(), "retry_decorator.py not created"
    content = decorator_file.read_text()
    assert "def with_retry_budget" in content, "with_retry_budget must be defined"


# ---------------------------------------------------------------------------
# CC-15: can_retry method present
# ---------------------------------------------------------------------------

def test_can_retry_method_present() -> None:
    """CC-15: RetryBudget.can_retry() method is defined."""
    project_dir = create_fixture_project(name="rb_t15")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "def can_retry" in content, "can_retry() method must be defined"


# ---------------------------------------------------------------------------
# CC-16: all_budget_stats function present
# ---------------------------------------------------------------------------

def test_all_budget_stats_present() -> None:
    """CC-16: all_budget_stats() function is defined for observability."""
    project_dir = create_fixture_project(name="rb_t16")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "def all_budget_stats" in content, "all_budget_stats() must be defined"


# ---------------------------------------------------------------------------
# CC-17: get_retry_budget factory function present
# ---------------------------------------------------------------------------

def test_get_retry_budget_factory_present() -> None:
    """CC-17: get_retry_budget() factory function is defined."""
    project_dir = create_fixture_project(name="rb_t17")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "def get_retry_budget" in content, "get_retry_budget() factory must be defined"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="rb_t18")
    result = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present with meaningful content
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention RETRY_BUDGET config."""
    project_dir = create_fixture_project(name="rb_t19")
    result = add_retry_budget(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps)
    assert "RETRY_BUDGET" in combined or "retry" in combined.lower()


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="rb_t20")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Domain-specific: MCP_TOOL entry matches function name
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """MCP_TOOL['entry'] must equal the function name 'add_retry_budget'."""
    from adapt.extend.infrastructure.add_retry_budget import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_retry_budget"


def test_mcp_tool_has_required_keys() -> None:
    """MCP_TOOL dict must have name, description, tags, entry keys."""
    from adapt.extend.infrastructure.add_retry_budget import MCP_TOOL
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


def test_retry_budget_uses_thread_lock() -> None:
    """retry_budget.py must use threading.Lock for concurrent safety."""
    project_dir = create_fixture_project(name="rb_t21")
    add_retry_budget(ToolInput(project_dir=str(project_dir)))
    budget_file = project_dir / "app" / "resilience" / "retry_budget.py"
    content = budget_file.read_text()
    assert "threading" in content or "Lock" in content, "Must use threading.Lock"


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run,
        test_files_created_count,
        test_files_modified_count,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_routes_registered,
        test_retry_budget_class_defined,
        test_budget_exhausted_error_defined,
        test_sliding_window_present,
        test_with_retry_budget_decorator_defined,
        test_can_retry_method_present,
        test_all_budget_stats_present,
        test_get_retry_budget_factory_present,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_mcp_tool_entry_matches_function,
        test_mcp_tool_has_required_keys,
        test_retry_budget_uses_thread_lock,
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
    print(f"TOOL-098 add_retry_budget: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
