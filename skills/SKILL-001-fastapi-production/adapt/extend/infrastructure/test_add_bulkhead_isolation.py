"""Tests for TOOL-097 add_bulkhead_isolation.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_bulkhead_isolation.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_bulkhead_isolation.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_bulkhead_isolation import add_bulkhead_isolation
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
    project_dir = create_fixture_project(name="bh_t01")
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="bh_t02")
    r1 = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="bh_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has >= 4 entries and all paths exist on disk."""
    project_dir = create_fixture_project(name="bh_t04")
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 created files, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has >= 1 entry and all paths exist on disk."""
    project_dir = create_fixture_project(name="bh_t05")
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 modified file, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All generated .py files pass ast.parse without SyntaxError."""
    project_dir = create_fixture_project(name="bh_t06")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="bh_t07")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    resilience_dir = project_dir / "app" / "resilience"
    middleware_dir = project_dir / "app" / "middleware"
    violations: list[str] = []
    for py_file in list(resilience_dir.rglob("*.py")) + list(middleware_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.lineno} {node.name}() = {loc} LOC")
    assert not violations, "Functions exceeding 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: Config fields appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="bh_t08")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "BULKHEAD_ENABLED" in content
    assert "    BULKHEAD_ENABLED" in content, "Config field must use 4-space indent"


# ---------------------------------------------------------------------------
# CC-09: bulkhead.py created with Bulkhead class
# ---------------------------------------------------------------------------

def test_bulkhead_file_created() -> None:
    """CC-09: app/resilience/bulkhead.py exists with Bulkhead class."""
    project_dir = create_fixture_project(name="bh_t09")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    bulkhead_file = project_dir / "app" / "resilience" / "bulkhead.py"
    assert bulkhead_file.exists(), "bulkhead.py not created"
    content = bulkhead_file.read_text()
    assert "Bulkhead" in content, "Bulkhead class must be defined"


# ---------------------------------------------------------------------------
# CC-10: semaphore-based concurrency control
# ---------------------------------------------------------------------------

def test_semaphore_based_control() -> None:
    """CC-10: Bulkhead uses asyncio.Semaphore for concurrency control."""
    project_dir = create_fixture_project(name="bh_t10")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    bulkhead_file = project_dir / "app" / "resilience" / "bulkhead.py"
    content = bulkhead_file.read_text()
    assert "Semaphore" in content, "Bulkhead must use asyncio.Semaphore"


# ---------------------------------------------------------------------------
# CC-11: pool_config.py created with BulkheadConfig
# ---------------------------------------------------------------------------

def test_pool_config_file_created() -> None:
    """CC-11: app/resilience/pool_config.py exists with BulkheadConfig."""
    project_dir = create_fixture_project(name="bh_t11")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    pool_config_file = project_dir / "app" / "resilience" / "pool_config.py"
    assert pool_config_file.exists(), "pool_config.py not created"
    content = pool_config_file.read_text()
    assert "BulkheadConfig" in content, "BulkheadConfig must be defined"


# ---------------------------------------------------------------------------
# CC-12: three default groups (payments, crud, analytics)
# ---------------------------------------------------------------------------

def test_three_default_groups() -> None:
    """CC-12: Default groups payments, crud, analytics are defined."""
    project_dir = create_fixture_project(name="bh_t12")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    pool_config_file = project_dir / "app" / "resilience" / "pool_config.py"
    content = pool_config_file.read_text()
    assert '"payments"' in content or "'payments'" in content
    assert '"crud"' in content or "'crud'" in content
    assert '"analytics"' in content or "'analytics'" in content


# ---------------------------------------------------------------------------
# CC-13: middleware created with BulkheadMiddleware
# ---------------------------------------------------------------------------

def test_middleware_file_created() -> None:
    """CC-13: app/middleware/bulkhead.py exists with BulkheadMiddleware."""
    project_dir = create_fixture_project(name="bh_t13")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "bulkhead.py"
    assert mw_file.exists(), "bulkhead.py middleware not created"
    content = mw_file.read_text()
    assert "BulkheadMiddleware" in content


# ---------------------------------------------------------------------------
# CC-14: 503 response in middleware
# ---------------------------------------------------------------------------

def test_middleware_returns_503_when_full() -> None:
    """CC-14: BulkheadMiddleware returns 503 when pool is full."""
    project_dir = create_fixture_project(name="bh_t14")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "bulkhead.py"
    content = mw_file.read_text()
    assert "503" in content, "Middleware must return 503 when bulkhead pool is full"


# ---------------------------------------------------------------------------
# CC-15: status route created
# ---------------------------------------------------------------------------

def test_status_route_created() -> None:
    """CC-15: app/api/routes/bulkhead_status.py exists with /resilience/bulkheads."""
    project_dir = create_fixture_project(name="bh_t15")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    status_route = project_dir / "app" / "api" / "routes" / "bulkhead_status.py"
    assert status_route.exists(), "bulkhead_status.py route not created"
    content = status_route.read_text()
    assert "/resilience/bulkheads" in content or "bulkheads" in content


# ---------------------------------------------------------------------------
# CC-16: BulkheadFullError defined
# ---------------------------------------------------------------------------

def test_bulkhead_full_error_defined() -> None:
    """CC-16: BulkheadFullError exception class is defined."""
    project_dir = create_fixture_project(name="bh_t16")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    bulkhead_file = project_dir / "app" / "resilience" / "bulkhead.py"
    content = bulkhead_file.read_text()
    assert "BulkheadFullError" in content, "BulkheadFullError must be defined"


# ---------------------------------------------------------------------------
# CC-17: X-Bulkhead-Group header in middleware
# ---------------------------------------------------------------------------

def test_x_bulkhead_group_header() -> None:
    """CC-17: Middleware includes X-Bulkhead-Group header in 503 response."""
    project_dir = create_fixture_project(name="bh_t17")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "middleware" / "bulkhead.py"
    content = mw_file.read_text()
    assert "X-Bulkhead-Group" in content, "Middleware must add X-Bulkhead-Group header"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="bh_t18")
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps guides developer to configure bulkhead isolation."""
    project_dir = create_fixture_project(name="bh_t19")
    result = add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert (
        "bulkhead" in combined
        or "enabled" in combined
        or "middleware" in combined
        or "pool" in combined
    )


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="bh_t20")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: classify_route function defined
# ---------------------------------------------------------------------------

def test_classify_route_defined() -> None:
    """classify_route() function maps paths to bulkhead groups."""
    project_dir = create_fixture_project(name="bh_t21")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    pool_config_file = project_dir / "app" / "resilience" / "pool_config.py"
    content = pool_config_file.read_text()
    assert "def classify_route" in content, "classify_route() must be defined"


# ---------------------------------------------------------------------------
# Extra: all four config fields present
# ---------------------------------------------------------------------------

def test_all_four_config_fields_present() -> None:
    """All four BULKHEAD_* config fields must be patched."""
    project_dir = create_fixture_project(name="bh_t22")
    add_bulkhead_isolation(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "BULKHEAD_ENABLED" in content
    assert "BULKHEAD_PAYMENTS_MAX" in content
    assert "BULKHEAD_CRUD_MAX" in content
    assert "BULKHEAD_ANALYTICS_MAX" in content


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
        test_bulkhead_file_created,
        test_semaphore_based_control,
        test_pool_config_file_created,
        test_three_default_groups,
        test_middleware_file_created,
        test_middleware_returns_503_when_full,
        test_status_route_created,
        test_bulkhead_full_error_defined,
        test_x_bulkhead_group_header,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_classify_route_defined,
        test_all_four_config_fields_present,
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
    print(f"TOOL-097 add_bulkhead_isolation: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
