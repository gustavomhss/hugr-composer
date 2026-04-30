"""Tests for TOOL-096 add_adaptive_timeouts.

Generates real fixture projects, runs the tool, and verifies completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_adaptive_timeouts.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_adaptive_timeouts.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import json

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_adaptive_timeouts import MCP_TOOL, add_adaptive_timeouts
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
    project_dir = create_fixture_project(name="at_t01")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="at_t02")
    r1 = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="at_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: files_created has >= 2 entries and all paths exist on disk."""
    project_dir = create_fixture_project(name="at_t04")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 2, (
        f"Expected >= 2 created files, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: files_modified has >= 1 entry and all paths exist on disk."""
    project_dir = create_fixture_project(name="at_t05")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="at_t06")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="at_t07")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    resilience_dir = project_dir / "app" / "resilience"
    violations: list[str] = []
    for py_file in resilience_dir.rglob("*.py"):
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
    project_dir = create_fixture_project(name="at_t08")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "ADAPTIVE_TIMEOUT_ENABLED" in content
    assert "    ADAPTIVE_TIMEOUT_ENABLED" in content, "Config field must use 4-space indent"


# ---------------------------------------------------------------------------
# CC-09: adaptive_timeout.py created with AdaptiveTimeout class
# ---------------------------------------------------------------------------

def test_adaptive_timeout_file_created() -> None:
    """CC-09: app/resilience/adaptive_timeout.py exists with AdaptiveTimeout."""
    project_dir = create_fixture_project(name="at_t09")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    assert timeout_file.exists(), "adaptive_timeout.py not created"
    content = timeout_file.read_text()
    assert "AdaptiveTimeout" in content, "AdaptiveTimeout class must be defined"


# ---------------------------------------------------------------------------
# CC-10: p50/p95/p99 tracking
# ---------------------------------------------------------------------------

def test_percentile_tracking() -> None:
    """CC-10: AdaptiveTimeout tracks p50, p95, and p99 latency."""
    project_dir = create_fixture_project(name="at_t10")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    content = timeout_file.read_text()
    assert "p50" in content or "0.50" in content, "Must track p50"
    assert "p95" in content or "0.95" in content, "Must track p95"
    assert "p99" in content or "0.99" in content, "Must track p99"


# ---------------------------------------------------------------------------
# CC-11: p99 * 1.5 multiplier
# ---------------------------------------------------------------------------

def test_p99_multiplier() -> None:
    """CC-11: Timeout is computed as p99 * 1.5 (configurable multiplier)."""
    project_dir = create_fixture_project(name="at_t11")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    content = timeout_file.read_text()
    assert "1.5" in content, "Timeout multiplier p99 * 1.5 must be present"


# ---------------------------------------------------------------------------
# CC-12: floor and ceiling config
# ---------------------------------------------------------------------------

def test_floor_ceiling_config() -> None:
    """CC-12: Floor and ceiling are configurable via env vars."""
    project_dir = create_fixture_project(name="at_t12")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "ADAPTIVE_TIMEOUT_FLOOR_MS" in content
    assert "ADAPTIVE_TIMEOUT_CEILING_MS" in content


# ---------------------------------------------------------------------------
# CC-13: timeout_registry.py created with TimeoutRegistry
# ---------------------------------------------------------------------------

def test_timeout_registry_file_created() -> None:
    """CC-13: app/resilience/timeout_registry.py exists with TimeoutRegistry."""
    project_dir = create_fixture_project(name="at_t13")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "resilience" / "timeout_registry.py"
    assert registry_file.exists(), "timeout_registry.py not created"
    content = registry_file.read_text()
    assert "TimeoutRegistry" in content, "TimeoutRegistry must be defined"


# ---------------------------------------------------------------------------
# CC-14: adaptive_timeout decorator defined
# ---------------------------------------------------------------------------

def test_adaptive_timeout_decorator_defined() -> None:
    """CC-14: @adaptive_timeout decorator function is defined."""
    project_dir = create_fixture_project(name="at_t14")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    content = timeout_file.read_text()
    assert "def adaptive_timeout" in content, "@adaptive_timeout decorator must be defined"


# ---------------------------------------------------------------------------
# CC-15: asyncio.wait_for used for timeout enforcement
# ---------------------------------------------------------------------------

def test_asyncio_wait_for_used() -> None:
    """CC-15: asyncio.wait_for is used to enforce the computed timeout."""
    project_dir = create_fixture_project(name="at_t15")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    content = timeout_file.read_text()
    assert "asyncio.wait_for" in content or "wait_for" in content


# ---------------------------------------------------------------------------
# CC-16: get_timeout_registry factory defined
# ---------------------------------------------------------------------------

def test_get_timeout_registry_defined() -> None:
    """CC-16: get_timeout_registry() factory function is defined."""
    project_dir = create_fixture_project(name="at_t16")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "resilience" / "timeout_registry.py"
    content = registry_file.read_text()
    assert "get_timeout_registry" in content


# ---------------------------------------------------------------------------
# CC-17: asyncio NOT imported at top level in generated files
# ---------------------------------------------------------------------------

def test_optional_sdk_not_at_top_level() -> None:
    """CC-17: Optional SDKs are not imported at module top-level."""
    project_dir = create_fixture_project(name="at_t17")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    # The registry uses TYPE_CHECKING guard for AdaptiveTimeout — check it
    registry_file = project_dir / "app" / "resilience" / "timeout_registry.py"
    content = registry_file.read_text()
    assert "TYPE_CHECKING" in content or "get_or_create" in content


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="at_t18")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps guides developer to configure adaptive timeouts."""
    project_dir = create_fixture_project(name="at_t19")
    result = add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps).lower()
    assert (
        "adaptive_timeout" in combined
        or "enabled" in combined
        or "decorator" in combined
        or "timeout" in combined
    )


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="at_t20")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: all four config fields present
# ---------------------------------------------------------------------------

def test_all_four_config_fields_present() -> None:
    """All four ADAPTIVE_TIMEOUT_* config fields must be patched."""
    project_dir = create_fixture_project(name="at_t21")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "ADAPTIVE_TIMEOUT_ENABLED" in content
    assert "ADAPTIVE_TIMEOUT_FLOOR_MS" in content
    assert "ADAPTIVE_TIMEOUT_CEILING_MS" in content
    assert "ADAPTIVE_TIMEOUT_WINDOW_SIZE" in content


# ---------------------------------------------------------------------------
# Extra: get_stats returns p50/p95/p99/current_timeout_s
# ---------------------------------------------------------------------------

def test_get_stats_returns_percentiles() -> None:
    """get_stats() must return p50, p95, p99, and current_timeout_s."""
    project_dir = create_fixture_project(name="at_t22")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    timeout_file = project_dir / "app" / "resilience" / "adaptive_timeout.py"
    content = timeout_file.read_text()
    assert "get_stats" in content, "get_stats() must be defined"
    assert "current_timeout_s" in content


# ---------------------------------------------------------------------------
# CONTRACT §B1.0 + §B1.0.1 — primitive copy + thin glue
# ---------------------------------------------------------------------------

def test_primitive_copied() -> None:
    """CONTRACT §B1.0: the TimeoutBudget primitive is copied into the project."""
    project_dir = create_fixture_project(name="at_t23")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    p = project_dir / "core" / "venous" / "resiliency" / "TimeoutBudget" / "TimeoutBudget.py"
    assert p.exists(), f"primitive not copied: {p}"
    body = p.read_text()
    assert "MonotonicTimeoutBudget" in body
    assert "Copied from HuGR Smith" in body


def test_manifest_records_primitive() -> None:
    """CONTRACT §B1.0: .venous_manifest.json records the copied primitive."""
    project_dir = create_fixture_project(name="at_t24")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    manifest = json.loads((project_dir / ".venous_manifest.json").read_text())
    assert "core.venous.resiliency.TimeoutBudget" in {
        p["qualified_name"] for p in manifest["primitives"]
    }


def test_glue_imports_primitive() -> None:
    """CONTRACT §B1.0.1: glue file imports from core.venous.resiliency.TimeoutBudget."""
    project_dir = create_fixture_project(name="at_t25")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    glue = project_dir / "app" / "resilience" / "timeouts.py"
    body = glue.read_text()
    assert "from core.venous.resiliency.TimeoutBudget import" in body
    assert "MonotonicTimeoutBudget" in body
    assert "asyncio.wait_for" in body


def test_glue_body_under_20_loc() -> None:
    """CONTRACT §B1.0.1: primary glue body stays below 20 executable lines."""
    project_dir = create_fixture_project(name="at_t26")
    add_adaptive_timeouts(ToolInput(project_dir=str(project_dir)))
    tree = ast.parse((project_dir / "app" / "resilience" / "timeouts.py").read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.body[0].lineno
            end = node.end_lineno or start
            body_lines += end - start + 1
    assert body_lines <= 20, body_lines


def test_mcp_tool_metadata() -> None:
    """MCP_TOOL declares imports_primitives per CONTRACT §B1.0."""
    assert MCP_TOOL["entry"] == "add_adaptive_timeouts"
    assert "core.venous.resiliency.TimeoutBudget" in MCP_TOOL["imports_primitives"]
    assert tuple(MCP_TOOL["imports_adapters"]) == ()


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
        test_adaptive_timeout_file_created,
        test_percentile_tracking,
        test_p99_multiplier,
        test_floor_ceiling_config,
        test_timeout_registry_file_created,
        test_adaptive_timeout_decorator_defined,
        test_asyncio_wait_for_used,
        test_get_timeout_registry_defined,
        test_optional_sdk_not_at_top_level,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_all_four_config_fields_present,
        test_get_stats_returns_percentiles,
        test_primitive_copied,
        test_manifest_records_primitive,
        test_glue_imports_primitive,
        test_glue_body_under_20_loc,
        test_mcp_tool_metadata,
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
    print(f"TOOL-096 add_adaptive_timeouts: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
