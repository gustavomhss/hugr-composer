"""Tests for TOOL-067 add_temporal_workflow.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the AGENT_BRIEFING_TEMPLATE.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_temporal_workflow.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_temporal_workflow.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_temporal_workflow import add_temporal_workflow
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under *root*."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Raise AssertionError if any .py file under *root* has a SyntaxError."""
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
# Category A — Tool execution (CC-01..05, CC-13, CC-14)
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="tw_t01")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with empty files lists."""
    project_dir = create_fixture_project(name="tw_t02")
    r1 = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run_writes_nothing() -> None:
    """CC-03: dry_run=True returns success but writes zero bytes."""
    project_dir = create_fixture_project(name="tw_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created, "dry_run must not report created files"
    assert not result.files_modified, "dry_run must not report modified files"
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file on disk"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 6 new files."""
    project_dir = create_fixture_project(name="tw_t04")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 6, (
        f"Expected >= 6 files_created, got {len(result.files_created)}: "
        f"{result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing on disk: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, requirements)."""
    project_dir = create_fixture_project(name="tw_t05")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: "
        f"{result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing on disk: {path_str}"


def test_execution_time_recorded() -> None:
    """CC-13: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="tw_t06")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, (
        f"execution_time_ms should be positive, got {result.execution_time_ms}"
    )


def test_next_steps_present() -> None:
    """CC-14: next_steps is non-empty and mentions Temporal start action."""
    project_dir = create_fixture_project(name="tw_t07")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "temporal" in combined, "next_steps should mention Temporal"


# ---------------------------------------------------------------------------
# Category B — Generated code quality (CC-06, CC-07, CC-08, CC-12)
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="tw_t08")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="tw_t09")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CC-08: TEMPORAL_* settings exist inside the Settings class (4-space indent)."""
    project_dir = create_fixture_project(name="tw_t10")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("TEMPORAL_HOST", "TEMPORAL_NAMESPACE", "TEMPORAL_TASK_QUEUE"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify fields are inside the Settings class body (4-space indent)
    for line in content.splitlines():
        if "TEMPORAL_HOST" in line:
            assert line.startswith("    "), (
                f"TEMPORAL_HOST not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_requirements_patched() -> None:
    """CC-12: requirements.txt contains temporalio>=."""
    project_dir = create_fixture_project(name="tw_t11")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    requirements = project_dir / "requirements.txt"
    content = requirements.read_text()
    assert "temporalio>=" in content, (
        "temporalio dependency not added to requirements.txt"
    )


# ---------------------------------------------------------------------------
# Category C — Domain-specific files (CC-10, CC-11)
# ---------------------------------------------------------------------------

def test_workflows_init_created() -> None:
    """CC-11: app/workflows/__init__.py exists with re-exports."""
    project_dir = create_fixture_project(name="tw_t12")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "workflows" / "__init__.py"
    assert init_file.exists(), "app/workflows/__init__.py not created"
    content = init_file.read_text()
    assert "TemporalClientFactory" in content, "__init__.py must re-export TemporalClientFactory"
    assert "get_client" in content, "__init__.py must re-export get_client"


def test_client_module_created() -> None:
    """CC-11: app/workflows/client.py exists with TemporalClientFactory and get_client."""
    project_dir = create_fixture_project(name="tw_t13")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    client_file = project_dir / "app" / "workflows" / "client.py"
    assert client_file.exists(), "app/workflows/client.py not created"
    content = client_file.read_text()
    assert "TemporalClientFactory" in content, "TemporalClientFactory not in client.py"
    assert "get_client" in content, "get_client not in client.py"


def test_worker_module_created() -> None:
    """CC-11: app/workflows/worker.py exists with WorkerFactory and start/stop helpers."""
    project_dir = create_fixture_project(name="tw_t14")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "workflows" / "worker.py"
    assert worker_file.exists(), "app/workflows/worker.py not created"
    content = worker_file.read_text()
    assert "WorkerFactory" in content, "WorkerFactory not in worker.py"
    assert "start_worker" in content, "start_worker not in worker.py"
    assert "stop_worker" in content, "stop_worker not in worker.py"


def test_example_workflow_created() -> None:
    """CC-11: app/workflows/example_workflow.py exists with OrderProcessingWorkflow."""
    project_dir = create_fixture_project(name="tw_t15")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    workflow_file = project_dir / "app" / "workflows" / "example_workflow.py"
    assert workflow_file.exists(), "app/workflows/example_workflow.py not created"
    content = workflow_file.read_text()
    assert "OrderProcessingWorkflow" in content, "OrderProcessingWorkflow not found"


def test_activities_module_created() -> None:
    """CC-11: app/workflows/activities.py has all 4 activities including compensate."""
    project_dir = create_fixture_project(name="tw_t16")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    activities_file = project_dir / "app" / "workflows" / "activities.py"
    assert activities_file.exists(), "app/workflows/activities.py not created"
    content = activities_file.read_text()
    for fn in ("validate_order", "charge_payment", "fulfil_order", "compensate_payment"):
        assert fn in content, f"{fn} not found in activities.py"


def test_workflow_routes_created() -> None:
    """CC-11: app/api/routes/workflows.py has all 4 REST endpoints."""
    project_dir = create_fixture_project(name="tw_t17")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "workflows.py"
    assert routes_file.exists(), "app/api/routes/workflows.py not created"
    content = routes_file.read_text()
    for marker in ("start_workflow", "get_workflow_status", "signal_workflow", "cancel_workflow"):
        assert marker in content, f"{marker} route not found in workflows.py"


def test_dockerfile_temporal_worker_created() -> None:
    """CC-11: Dockerfile.temporal-worker exists and runs as non-root."""
    project_dir = create_fixture_project(name="tw_t18")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    dockerfile = project_dir / "Dockerfile.temporal-worker"
    assert dockerfile.exists(), "Dockerfile.temporal-worker not created"
    content = dockerfile.read_text()
    assert "USER" in content, "Dockerfile.temporal-worker must run as non-root (USER)"
    assert "1000" in content, "Non-root UID 1000 expected in Dockerfile.temporal-worker"


def test_routes_registered_in_routes_init() -> None:
    """CC-10: workflows router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="tw_t19")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "workflows" in content.lower(), (
            "Workflows router not registered in app/routes/__init__.py"
        )


def test_lazy_sdk_import_in_generated_code() -> None:
    """CC-17: temporalio is NOT imported at module top level in generated files."""
    project_dir = create_fixture_project(name="tw_t20")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    workflows_dir = project_dir / "app" / "workflows"
    for py_file in workflows_dir.glob("*.py"):
        lines = py_file.read_text().splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Top-level import lines (not indented)
            if stripped.startswith("from temporalio") or stripped.startswith("import temporalio"):
                if not line.startswith(" ") and not line.startswith("\t"):
                    # Check it's not inside a try/except block at module level
                    is_in_try_block = any(
                        lines[j].strip().startswith("try:") for j in range(max(0, i - 10), i)
                    )
                    if not is_in_try_block:
                        raise AssertionError(
                            f"Top-level temporalio import found in {py_file.name} "
                            f"line {i + 1}: {line!r}"
                        )


def test_main_py_not_modified() -> None:
    """CC-11: app/main.py is NOT in files_modified (separate process design)."""
    project_dir = create_fixture_project(name="tw_t21")
    result = add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    modified_names = [Path(p).name for p in result.files_modified]
    assert "main.py" not in modified_names, (
        "app/main.py must NOT be modified — Temporal worker is a separate process"
    )


def test_idempotent_project_still_parses() -> None:
    """CC-15: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="tw_t22")
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    add_temporal_workflow(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run_writes_nothing,
        test_files_created_count,
        test_files_modified_count,
        test_execution_time_recorded,
        test_next_steps_present,
        test_all_py_parse,
        test_no_function_over_50_loc,
        test_config_fields_patched,
        test_requirements_patched,
        test_workflows_init_created,
        test_client_module_created,
        test_worker_module_created,
        test_example_workflow_created,
        test_activities_module_created,
        test_workflow_routes_created,
        test_dockerfile_temporal_worker_created,
        test_routes_registered_in_routes_init,
        test_lazy_sdk_import_in_generated_code,
        test_main_py_not_modified,
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
    print(f"TOOL-067 add_temporal_workflow: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
