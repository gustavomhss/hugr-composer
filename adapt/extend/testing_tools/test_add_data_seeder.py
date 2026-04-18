"""Structural tests for TOOL-105 add_data_seeder.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/testing_tools/test_add_data_seeder.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/testing_tools/test_add_data_seeder.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.testing_tools.add_data_seeder import add_data_seeder
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
    project_dir = create_fixture_project(name="ds_t01")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="ds_t02")
    r1 = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="ds_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_data_seeder(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 5 new files (seeder pkg, generators, graph, route, script)."""
    project_dir = create_fixture_project(name="ds_t04")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config or routes init)."""
    project_dir = create_fixture_project(name="ds_t05")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="ds_t06")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="ds_t07")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CC-08: SEEDER_* fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="ds_t08")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("SEEDER_ENABLED", "SEEDER_DEFAULT_COUNT"):
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "SEEDER_ENABLED" in line:
            assert line.startswith("    "), (
                f"SEEDER_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


def test_routes_registered() -> None:
    """CC-10: Seeder router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="ds_t09")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "seeder" in content.lower(), "Seeder router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------

def test_data_seeder_module_created() -> None:
    """CC-11: app/seeder/__init__.py exists with DataSeeder class."""
    project_dir = create_fixture_project(name="ds_t10")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    seeder_init = project_dir / "app" / "seeder" / "__init__.py"
    assert seeder_init.exists(), "app/seeder/__init__.py not created"
    content = seeder_init.read_text()
    assert "DataSeeder" in content, "DataSeeder class not found in seeder/__init__.py"


def test_generators_module_created() -> None:
    """CC-12: app/seeder/generators.py exists with FieldGenerator."""
    project_dir = create_fixture_project(name="ds_t11")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    generators = project_dir / "app" / "seeder" / "generators.py"
    assert generators.exists(), "app/seeder/generators.py not created"
    content = generators.read_text()
    assert "FieldGenerator" in content, "FieldGenerator not found in generators.py"


def test_dependency_graph_module_created() -> None:
    """CC-13: app/seeder/graph.py exists with DependencyGraph."""
    project_dir = create_fixture_project(name="ds_t12")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    graph = project_dir / "app" / "seeder" / "graph.py"
    assert graph.exists(), "app/seeder/graph.py not created"
    content = graph.read_text()
    assert "DependencyGraph" in content, "DependencyGraph not found in graph.py"
    assert "topological_order" in content, "topological_order method not found"


def test_dev_seed_route_created() -> None:
    """CC-14: app/api/routes/seeder.py exists with POST /dev/seed route."""
    project_dir = create_fixture_project(name="ds_t13")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    seeder_route = project_dir / "app" / "api" / "routes" / "seeder.py"
    assert seeder_route.exists(), "app/api/routes/seeder.py not created"
    content = seeder_route.read_text()
    assert "/dev/seed" in content or '"/seed"' in content, "POST /dev/seed route not found"
    assert "SEEDER_ENABLED" in content, "SEEDER_ENABLED guard not found in route"


def test_seed_cli_script_created() -> None:
    """CC-15: scripts/seed.py CLI script exists."""
    project_dir = create_fixture_project(name="ds_t14")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    seed_script = project_dir / "scripts" / "seed.py"
    assert seed_script.exists(), "scripts/seed.py not created"
    content = seed_script.read_text()
    assert "--count" in content, "--count argument not found in seed.py"
    assert "DataSeeder" in content, "DataSeeder not used in seed.py"


def test_production_guard_in_route() -> None:
    """CC-16: /dev/seed returns 404 when SEEDER_ENABLED=false (production guard)."""
    project_dir = create_fixture_project(name="ds_t15")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    seeder_route = project_dir / "app" / "api" / "routes" / "seeder.py"
    content = seeder_route.read_text()
    assert "404" in content or "not enabled" in content.lower(), (
        "Route should return 404 when SEEDER_ENABLED=false"
    )


def test_smart_generators_email_name() -> None:
    """CC-17: FieldGenerator has email and name generation logic."""
    project_dir = create_fixture_project(name="ds_t16")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    generators = project_dir / "app" / "seeder" / "generators.py"
    content = generators.read_text()
    assert "email" in content.lower(), "Email generation not found in generators.py"
    assert "name" in content.lower(), "Name generation not found in generators.py"


def test_topological_sort_kahn() -> None:
    """CC-18: DependencyGraph uses Kahn's algorithm (deque/BFS)."""
    project_dir = create_fixture_project(name="ds_t17")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    graph = project_dir / "app" / "seeder" / "graph.py"
    content = graph.read_text()
    assert "deque" in content, "DependencyGraph should use deque for Kahn's algorithm"
    assert "in_degree" in content, "DependencyGraph should track in_degree for topological sort"


def test_no_hardcoded_secrets() -> None:
    """CC-19: No hardcoded secrets/API keys in generated templates."""
    project_dir = create_fixture_project(name="ds_t18")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    seeder_dir = project_dir / "app" / "seeder"
    for py_file in sorted(seeder_dir.rglob("*.py")):
        content = py_file.read_text()
        for bad in ('password="', 'secret="', 'api_key="'):
            assert bad not in content, (
                f"Potential hardcoded secret in {py_file.name}: {bad}"
            )


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="ds_t19")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps mentions SEEDER_ENABLED."""
    project_dir = create_fixture_project(name="ds_t20")
    result = add_data_seeder(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "seeder_enabled" in combined, "next_steps should mention SEEDER_ENABLED"


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="ds_t21")
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    add_data_seeder(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.testing_tools.add_data_seeder import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_data_seeder", (
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
        test_routes_registered,
        test_data_seeder_module_created,
        test_generators_module_created,
        test_dependency_graph_module_created,
        test_dev_seed_route_created,
        test_seed_cli_script_created,
        test_production_guard_in_route,
        test_smart_generators_email_name,
        test_topological_sort_kahn,
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
    print(f"TOOL-105 add_data_seeder: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
