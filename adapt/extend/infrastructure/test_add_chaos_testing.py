"""Structural tests for TOOL-099 add_chaos_testing.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_chaos_testing.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_chaos_testing.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_chaos_testing import add_chaos_testing
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
    project_dir = create_fixture_project(name="ct_t01")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Running the tool twice returns no_op on second run."""
    project_dir = create_fixture_project(name="ct_t02")
    r1 = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run writes nothing
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ct_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir), dry_run=True))
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
    project_dir = create_fixture_project(name="ct_t04")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="ct_t05")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="ct_t06")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ct_t07")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_dir = project_dir / "app" / "chaos"
    violations: list[str] = []
    for py_file in sorted(chaos_dir.rglob("*.py")):
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
    """CC-08: CHAOS_* fields appear in config.py with 4-space indent."""
    project_dir = create_fixture_project(name="ct_t08")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    assert config_file.exists()
    content = config_file.read_text()
    assert "CHAOS_ENABLED" in content, "CHAOS_ENABLED missing from config"
    assert "CHAOS_LATENCY_MS" in content, "CHAOS_LATENCY_MS missing from config"
    assert "CHAOS_ERROR_RATE" in content, "CHAOS_ERROR_RATE missing from config"
    for line in content.splitlines():
        if "CHAOS_" in line and ":" in line and "#" not in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-10: routes file created
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: app/api/routes/chaos.py is created with router."""
    project_dir = create_fixture_project(name="ct_t10")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_route = project_dir / "app" / "api" / "routes" / "chaos.py"
    assert chaos_route.exists(), "chaos.py routes file not created"
    content = chaos_route.read_text()
    assert "router" in content, "router not defined in chaos.py"


# ---------------------------------------------------------------------------
# CC-11: ChaosEngine class defined
# ---------------------------------------------------------------------------

def test_chaos_engine_class_defined() -> None:
    """CC-11: ChaosEngine class is defined in app/chaos/__init__.py."""
    project_dir = create_fixture_project(name="ct_t11")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_init = project_dir / "app" / "chaos" / "__init__.py"
    assert chaos_init.exists(), "app/chaos/__init__.py not created"
    content = chaos_init.read_text()
    assert "class ChaosEngine" in content, "ChaosEngine class must be defined"


# ---------------------------------------------------------------------------
# CC-12: injectors defined
# ---------------------------------------------------------------------------

def test_injectors_defined() -> None:
    """CC-12: LatencyInjector, ErrorInjector, TimeoutInjector all present."""
    project_dir = create_fixture_project(name="ct_t12")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    injectors_file = project_dir / "app" / "chaos" / "injectors.py"
    assert injectors_file.exists(), "injectors.py not created"
    content = injectors_file.read_text()
    assert "LatencyInjector" in content, "LatencyInjector must be defined"
    assert "ErrorInjector" in content, "ErrorInjector must be defined"
    assert "TimeoutInjector" in content, "TimeoutInjector must be defined"


# ---------------------------------------------------------------------------
# CC-13: production guard hardcoded
# ---------------------------------------------------------------------------

def test_production_guard_hardcoded() -> None:
    """CC-13: Production guard 'production' is hardcoded in ChaosEngine.enable()."""
    project_dir = create_fixture_project(name="ct_t13")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_init = project_dir / "app" / "chaos" / "__init__.py"
    content = chaos_init.read_text()
    assert "production" in content, "Production guard must be hardcoded"


# ---------------------------------------------------------------------------
# CC-14: middleware defined
# ---------------------------------------------------------------------------

def test_chaos_middleware_defined() -> None:
    """CC-14: ChaosMiddleware is defined in app/chaos/middleware.py."""
    project_dir = create_fixture_project(name="ct_t14")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "chaos" / "middleware.py"
    assert middleware_file.exists(), "middleware.py not created"
    content = middleware_file.read_text()
    assert "ChaosMiddleware" in content, "ChaosMiddleware must be defined"


# ---------------------------------------------------------------------------
# CC-15: enable endpoint present
# ---------------------------------------------------------------------------

def test_enable_endpoint_present() -> None:
    """CC-15: POST /chaos/enable endpoint is defined in routes."""
    project_dir = create_fixture_project(name="ct_t15")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_route = project_dir / "app" / "api" / "routes" / "chaos.py"
    content = chaos_route.read_text()
    assert "enable_chaos" in content or "/enable" in content, (
        "enable endpoint must be present"
    )


# ---------------------------------------------------------------------------
# CC-16: disable and status endpoints present
# ---------------------------------------------------------------------------

def test_disable_and_status_endpoints_present() -> None:
    """CC-16: POST /chaos/disable and GET /chaos/status are defined."""
    project_dir = create_fixture_project(name="ct_t16")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_route = project_dir / "app" / "api" / "routes" / "chaos.py"
    content = chaos_route.read_text()
    assert "disable" in content, "disable endpoint must be present"
    assert "status" in content, "status endpoint must be present"


# ---------------------------------------------------------------------------
# CC-17: CHAOS_ENABLED defaults to false
# ---------------------------------------------------------------------------

def test_chaos_enabled_defaults_false() -> None:
    """CC-17: CHAOS_ENABLED config field defaults to False."""
    project_dir = create_fixture_project(name="ct_t17")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "CHAOS_ENABLED" in content
    # Find the line and verify default is False
    for line in content.splitlines():
        if "CHAOS_ENABLED" in line and "=" in line:
            assert "False" in line or "false" in line, (
                f"CHAOS_ENABLED must default to False, got: {line!r}"
            )


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms positive
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ct_t18")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


# ---------------------------------------------------------------------------
# CC-N: next_steps present and relevant
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must be non-empty and mention CHAOS_ENABLED."""
    project_dir = create_fixture_project(name="ct_t19")
    result = add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0
    combined = " ".join(result.next_steps)
    assert "CHAOS" in combined or "chaos" in combined.lower()


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ct_t20")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Domain-specific: MCP_TOOL validation
# ---------------------------------------------------------------------------

def test_mcp_tool_entry_matches_function() -> None:
    """MCP_TOOL['entry'] must equal 'add_chaos_testing'."""
    from adapt.extend.infrastructure.add_chaos_testing import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_chaos_testing"


def test_mcp_tool_has_required_keys() -> None:
    """MCP_TOOL dict must have name, description, tags, entry keys."""
    from adapt.extend.infrastructure.add_chaos_testing import MCP_TOOL
    for key in ("name", "description", "tags", "entry"):
        assert key in MCP_TOOL, f"MCP_TOOL missing key: {key}"


def test_get_chaos_engine_factory_present() -> None:
    """get_chaos_engine() factory must be defined for shared state."""
    project_dir = create_fixture_project(name="ct_t21")
    add_chaos_testing(ToolInput(project_dir=str(project_dir)))
    chaos_init = project_dir / "app" / "chaos" / "__init__.py"
    content = chaos_init.read_text()
    assert "def get_chaos_engine" in content, "get_chaos_engine() must be defined"


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
        test_chaos_engine_class_defined,
        test_injectors_defined,
        test_production_guard_hardcoded,
        test_chaos_middleware_defined,
        test_enable_endpoint_present,
        test_disable_and_status_endpoints_present,
        test_chaos_enabled_defaults_false,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_mcp_tool_entry_matches_function,
        test_mcp_tool_has_required_keys,
        test_get_chaos_engine_factory_present,
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
    print(f"TOOL-099 add_chaos_testing: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
