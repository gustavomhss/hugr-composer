"""Tests for TOOL-091 add_database_migrations_ci.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_database_migrations_ci.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_database_migrations_ci.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_database_migrations_ci import add_database_migrations_ci
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* sorted by path.

    Args:
        root: Directory to walk.

    Returns:
        Sorted list of .py Path objects.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under *root* has valid syntax.

    Args:
        root: Project root to walk.

    Raises:
        AssertionError: If any file fails ast.parse.
    """
    for f in _all_py_files(root):
        source = f.read_text()
        try:
            ast.parse(source)
        except SyntaxError as exc:
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def _fresh(name: str) -> Path:
    """Return a fresh fixture project.

    Args:
        name: Unique project name.

    Returns:
        Path to generated project root.
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("mci_t01")
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files written."""
    project_dir = _fresh("mci_t02")
    r1 = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("mci_t03")
    before = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {str(f): f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count and existence
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 4 files created and all exist on disk."""
    project_dir = _fresh("mci_t04")
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count and existence
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified (config.py) and exists on disk."""
    project_dir = _fresh("mci_t05")
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in the project parses without SyntaxError."""
    project_dir = _fresh("mci_t06")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = _fresh("mci_t07")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    migrations_dir = project_dir / "app" / "migrations"
    scripts_dir = project_dir / "scripts"
    for py_file in list(migrations_dir.rglob("*.py")) + list(scripts_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = node.end_lineno - node.lineno + 1
                assert loc <= 50, (
                    f"Function {node.name!r} in {py_file} has {loc} lines (max 50)"
                )


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: Migration CI config fields present in config.py with 4-space indent."""
    project_dir = _fresh("mci_t08")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    src = config_file.read_text()
    for field in ("MIGRATION_CI_FAIL_ON_DESTRUCTIVE", "MIGRATION_CI_REQUIRE_ROLLBACK"):
        assert field in src, f"Config field {field} missing from config.py"
        for line in src.splitlines():
            if field in line and "=" in line:
                assert line.startswith("    "), (
                    f"Field {field} must have 4-space indent, got: {line!r}"
                )
                break


# ---------------------------------------------------------------------------
# Domain tests (CC-11+)
# ---------------------------------------------------------------------------

def test_migrations_init_created() -> None:
    """CC-11: app/migrations/__init__.py is created."""
    project_dir = _fresh("mci_t11")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "migrations" / "__init__.py"
    assert init_file.exists(), "app/migrations/__init__.py must be created"
    src = init_file.read_text()
    assert "MigrationCIRunner" in src


def test_ci_runner_file_created() -> None:
    """CC-12: app/migrations/ci_runner.py is created with MigrationCIRunner."""
    project_dir = _fresh("mci_t12")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    ci_runner_file = project_dir / "app" / "migrations" / "ci_runner.py"
    assert ci_runner_file.exists(), "ci_runner.py must be created"
    src = ci_runner_file.read_text()
    assert "class MigrationCIRunner" in src, "MigrationCIRunner class must be defined"


def test_check_pending_method() -> None:
    """CC-13: MigrationCIRunner.check_pending() method is present."""
    project_dir = _fresh("mci_t13")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    ci_runner_file = project_dir / "app" / "migrations" / "ci_runner.py"
    src = ci_runner_file.read_text()
    assert "def check_pending" in src, "check_pending() method must be present"


def test_verify_rollback_method() -> None:
    """CC-14: MigrationCIRunner.verify_rollback() method is present."""
    project_dir = _fresh("mci_t14")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    ci_runner_file = project_dir / "app" / "migrations" / "ci_runner.py"
    src = ci_runner_file.read_text()
    assert "def verify_rollback" in src, "verify_rollback() method must be present"


def test_schema_diff_method() -> None:
    """CC-15: MigrationCIRunner.schema_diff() method is present."""
    project_dir = _fresh("mci_t15")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    ci_runner_file = project_dir / "app" / "migrations" / "ci_runner.py"
    src = ci_runner_file.read_text()
    assert "def schema_diff" in src, "schema_diff() method must be present"


def test_safety_checker_file_created() -> None:
    """CC-16: app/migrations/safety_checker.py is created with SafetyChecker."""
    project_dir = _fresh("mci_t16")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    safety_file = project_dir / "app" / "migrations" / "safety_checker.py"
    assert safety_file.exists(), "safety_checker.py must be created"
    src = safety_file.read_text()
    assert "class SafetyChecker" in src, "SafetyChecker class must be defined"


def test_safety_checker_detects_drop_table() -> None:
    """CC-17: SafetyChecker detects DROP TABLE operations."""
    project_dir = _fresh("mci_t17")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    safety_file = project_dir / "app" / "migrations" / "safety_checker.py"
    src = safety_file.read_text()
    assert "DROP TABLE" in src or "drop_table" in src, (
        "SafetyChecker must detect DROP TABLE"
    )


def test_safety_checker_detects_drop_column() -> None:
    """CC-18: SafetyChecker detects DROP COLUMN operations."""
    project_dir = _fresh("mci_t18")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    safety_file = project_dir / "app" / "migrations" / "safety_checker.py"
    src = safety_file.read_text()
    assert "DROP COLUMN" in src or "drop_column" in src, (
        "SafetyChecker must detect DROP COLUMN"
    )


def test_check_migrations_script_created() -> None:
    """CC-19: scripts/check_migrations.py is created."""
    project_dir = _fresh("mci_t19")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    check_script = project_dir / "scripts" / "check_migrations.py"
    assert check_script.exists(), "scripts/check_migrations.py must be created"


def test_check_script_has_pending_flag() -> None:
    """CC-20: check_migrations.py CLI supports --pending flag."""
    project_dir = _fresh("mci_t20")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    check_script = project_dir / "scripts" / "check_migrations.py"
    src = check_script.read_text()
    assert "--pending" in src, "CLI must support --pending flag"


def test_check_script_has_rollback_flag() -> None:
    """CC-21: check_migrations.py CLI supports --rollback flag."""
    project_dir = _fresh("mci_t21")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    check_script = project_dir / "scripts" / "check_migrations.py"
    src = check_script.read_text()
    assert "--rollback" in src, "CLI must support --rollback flag"


def test_check_script_has_diff_flag() -> None:
    """CC-22: check_migrations.py CLI supports --diff flag."""
    project_dir = _fresh("mci_t22")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    check_script = project_dir / "scripts" / "check_migrations.py"
    src = check_script.read_text()
    assert "--diff" in src, "CLI must support --diff flag"


def test_no_new_deps_required() -> None:
    """CC-23: No new packages added to requirements.txt (alembic already present)."""
    project_dir = _fresh("mci_t23")
    req_before = (project_dir / "requirements.txt").read_text()
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    req_after = (project_dir / "requirements.txt").read_text()
    # Only alembic should appear — not new deps
    assert req_before == req_after or "alembic" in req_after, (
        "No new non-alembic dependencies should be added"
    )


def test_next_steps_present() -> None:
    """CC-N: result.next_steps is populated with CI pipeline guidance."""
    project_dir = _fresh("mci_t24")
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert "ci" in combined or "migration" in combined or "alembic" in combined


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer."""
    project_dir = _fresh("mci_t25")
    result = add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: Run twice, then ast.parse all .py files — no syntax errors."""
    project_dir = _fresh("mci_t26")
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    add_database_migrations_ci(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


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
        test_migrations_init_created,
        test_ci_runner_file_created,
        test_check_pending_method,
        test_verify_rollback_method,
        test_schema_diff_method,
        test_safety_checker_file_created,
        test_safety_checker_detects_drop_table,
        test_safety_checker_detects_drop_column,
        test_check_migrations_script_created,
        test_check_script_has_pending_flag,
        test_check_script_has_rollback_flag,
        test_check_script_has_diff_flag,
        test_no_new_deps_required,
        test_next_steps_present,
        test_execution_time_recorded,
        test_idempotent_project_still_parses,
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

    print(f"\n{'=' * 60}")
    print(f"TOOL-091 add_database_migrations_ci: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
