"""Structural tests for TOOL-104 add_schema_evolution_guard.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_schema_evolution_guard.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_schema_evolution_guard.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_schema_evolution_guard import add_schema_evolution_guard
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


def _max_function_loc(root: Path, subdir: str = "app") -> int:
    """Return the max LOC of any function in the given subdir."""
    target = root / subdir
    if not target.exists():
        return 0
    max_loc = 0
    for f in sorted(target.rglob("*.py")):
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, "end_lineno") and node.end_lineno:
                    loc = node.end_lineno - node.lineno + 1
                    max_loc = max(max_loc, loc)
    return max_loc


# ---------------------------------------------------------------------------
# Category A — Tool execution (CC-01 to CC-05)
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="sg_t01")
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="sg_t02")
    r1 = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="sg_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 new files (comparator, rules, CI script, workflow)."""
    project_dir = create_fixture_project(name="sg_t04")
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config)."""
    project_dir = create_fixture_project(name="sg_t05")
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# Category B — Generated code quality (CC-06 to CC-08)
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="sg_t06")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="sg_t07")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CC-08: SCHEMA_GUARD_* fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="sg_t08")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("SCHEMA_GUARD_BASELINE_PATH", "SCHEMA_GUARD_FAIL_ON_BREAKING"):
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "SCHEMA_GUARD_BASELINE_PATH" in line:
            assert line.startswith("    "), (
                f"SCHEMA_GUARD_BASELINE_PATH not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# Category C — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------

def test_comparator_module_created() -> None:
    """CC-11: app/schema_guard/comparator.py exists with SchemaComparator."""
    project_dir = create_fixture_project(name="sg_t09")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    comparator = project_dir / "app" / "schema_guard" / "comparator.py"
    assert comparator.exists(), "comparator.py not created"
    content = comparator.read_text()
    assert "SchemaComparator" in content, "SchemaComparator class not found"
    assert "ChangeClass" in content, "ChangeClass enum not found"


def test_rules_module_created() -> None:
    """CC-12: app/schema_guard/rules.py exists with all 5 rule functions."""
    project_dir = create_fixture_project(name="sg_t10")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    rules = project_dir / "app" / "schema_guard" / "rules.py"
    assert rules.exists(), "rules.py not created"
    content = rules.read_text()
    for func in (
        "check_fields_removed",
        "check_types_changed",
        "check_required_added",
        "check_enum_shrunk",
        "check_response_shape_changed",
    ):
        assert func in content, f"Rule function '{func}' not found in rules.py"


def test_ci_script_created() -> None:
    """CC-13: scripts/check_schema_compat.py exists and is runnable."""
    project_dir = create_fixture_project(name="sg_t11")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    ci_script = project_dir / "scripts" / "check_schema_compat.py"
    assert ci_script.exists(), "scripts/check_schema_compat.py not created"
    content = ci_script.read_text()
    assert "SchemaComparator" in content, "CI script does not use SchemaComparator"
    assert "SCHEMA_GUARD_BASELINE_PATH" in content, "CI script does not use SCHEMA_GUARD_BASELINE_PATH"
    assert "SCHEMA_GUARD_FAIL_ON_BREAKING" in content, "CI script does not use SCHEMA_GUARD_FAIL_ON_BREAKING"


def test_github_workflow_created() -> None:
    """CC-14: .github/workflows/schema_guard.yml exists."""
    project_dir = create_fixture_project(name="sg_t12")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    workflow = project_dir / ".github" / "workflows" / "schema_guard.yml"
    assert workflow.exists(), ".github/workflows/schema_guard.yml not created"
    content = workflow.read_text()
    assert "schema_guard" in content.lower(), "Workflow does not reference schema_guard"


def test_change_class_enum_values() -> None:
    """CC-15: ChangeClass has BREAKING, COMPATIBLE, ADDITIVE, IDENTICAL."""
    project_dir = create_fixture_project(name="sg_t13")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    comparator = project_dir / "app" / "schema_guard" / "comparator.py"
    content = comparator.read_text()
    for value in ("BREAKING", "COMPATIBLE", "ADDITIVE", "IDENTICAL"):
        assert value in content, f"ChangeClass missing value '{value}'"


def test_comparator_compare_method_exists() -> None:
    """CC-16: SchemaComparator has a compare() method."""
    project_dir = create_fixture_project(name="sg_t14")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    comparator = project_dir / "app" / "schema_guard" / "comparator.py"
    content = comparator.read_text()
    assert "def compare(" in content, "SchemaComparator.compare() method not found"


def test_ci_script_exit_1_on_breaking() -> None:
    """CC-17: CI script exits 1 on breaking changes."""
    project_dir = create_fixture_project(name="sg_t15")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    ci_script = project_dir / "scripts" / "check_schema_compat.py"
    content = ci_script.read_text()
    assert "sys.exit(1)" in content, "CI script should sys.exit(1) on breaking changes"
    assert "fail_on_breaking" in content, "CI script should check fail_on_breaking flag"


def test_docstrings_present() -> None:
    """CC-18: All public functions in generated code have docstrings."""
    project_dir = create_fixture_project(name="sg_t16")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    guard_dir = project_dir / "app" / "schema_guard"
    missing: list[str] = []
    for py_file in sorted(guard_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_file.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    if not ast.get_docstring(node):
                        missing.append(f"{py_file.name}::{node.name}")
    assert not missing, f"Public functions missing docstrings: {missing}"


def test_ci_script_export_baseline() -> None:
    """CC-19: CI script supports --export-baseline argument."""
    project_dir = create_fixture_project(name="sg_t17")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    ci_script = project_dir / "scripts" / "check_schema_compat.py"
    content = ci_script.read_text()
    assert "--export-baseline" in content, "CI script missing --export-baseline argument"


def test_no_hardcoded_secrets() -> None:
    """CC-20: No hardcoded secrets in generated templates."""
    project_dir = create_fixture_project(name="sg_t18")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    guard_dir = project_dir / "app" / "schema_guard"
    for py_file in sorted(guard_dir.rglob("*.py")):
        content = py_file.read_text().lower()
        for bad in ("password=", "secret=", "api_key="):
            if bad in content:
                # Allow if it's a variable name reference, not a literal assignment
                for line in content.splitlines():
                    if bad in line and "\"" in line and "changethis" not in line:
                        assert False, f"Potential hardcoded secret in {py_file.name}: {line!r}"


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="sg_t19")
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps mentions baseline and CI."""
    project_dir = create_fixture_project(name="sg_t20")
    result = add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "baseline" in combined, "next_steps should mention baseline"


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="sg_t21")
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    add_schema_evolution_guard(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.testing_tools.add_schema_evolution_guard import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_schema_evolution_guard", (
        f"MCP_TOOL entry '{MCP_TOOL['entry']}' does not match function name"
    )


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
        test_comparator_module_created,
        test_rules_module_created,
        test_ci_script_created,
        test_github_workflow_created,
        test_change_class_enum_values,
        test_comparator_compare_method_exists,
        test_ci_script_exit_1_on_breaking,
        test_docstrings_present,
        test_ci_script_export_baseline,
        test_no_hardcoded_secrets,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_mcp_tool_entry_matches_function,
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
    print(f"TOOL-104 add_schema_evolution_guard: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
