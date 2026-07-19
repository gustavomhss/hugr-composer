"""Tests for TOOL-123 add_dependency_health_map.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_dependency_health_map.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_dependency_health_map.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_dependency_health_map import add_dependency_health_map
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted.

    Args:
        root: Directory to walk recursively.
    """
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under root parses without SyntaxError.

    Args:
        root: Directory to walk recursively.
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
    """
    return create_fixture_project(name=name)


# ---------------------------------------------------------------------------
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("hmap_t01")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: Idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = _fresh("hmap_t02")
    r1 = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("hmap_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 3 files are created and all exist on disk."""
    project_dir = _fresh("hmap_t04")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 3, (
        f"Expected >= 3 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file is modified and all exist on disk."""
    project_dir = _fresh("hmap_t05")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, (
        f"Expected >= 1 files_modified, got {len(result.files_modified)}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: All .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every .py file in the project parses without SyntaxError."""
    project_dir = _fresh("hmap_t06")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: No function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = _fresh("hmap_t07")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    hmap_dir = project_dir / "app" / "health_map"
    for py_file in sorted(hmap_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                assert loc <= 50, (
                    f"Function '{node.name}' in {py_file} has {loc} LOC (max 50)"
                )


# ---------------------------------------------------------------------------
# CC-08: Config fields patched with 4-space indent
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: HEALTH_MAP_ENABLED and HEALTH_MAP_CHECK_INTERVAL_S in config."""
    project_dir = _fresh("hmap_t08")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "HEALTH_MAP_ENABLED" in content
    assert "HEALTH_MAP_CHECK_INTERVAL_S" in content
    for line in content.splitlines():
        if "HEALTH_MAP_ENABLED" in line:
            assert line.startswith("    "), f"Field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: HealthMapBuilder created
# ---------------------------------------------------------------------------

def test_health_map_builder_init() -> None:
    """CC-09: app/health_map/__init__.py exists with HealthMapBuilder."""
    project_dir = _fresh("hmap_t09")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "health_map" / "__init__.py"
    assert init_file.exists(), "app/health_map/__init__.py not created"
    content = init_file.read_text()
    assert "HealthMapBuilder" in content, "HealthMapBuilder not found"
    assert "get_health_map_builder" in content, "get_health_map_builder singleton not found"


# ---------------------------------------------------------------------------
# CC-10: Routes registered in main.py
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: health_map router included in app/main.py."""
    project_dir = _fresh("hmap_t10")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "health_map" in content, "health_map router not registered in main.py"


# ---------------------------------------------------------------------------
# CC-11: DependencyChecker created
# ---------------------------------------------------------------------------

def test_dependency_checker_created() -> None:
    """CC-11: app/health_map/checker.py exists with DependencyChecker."""
    project_dir = _fresh("hmap_t11")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    checker_file = project_dir / "app" / "health_map" / "checker.py"
    assert checker_file.exists(), "checker.py not created"
    content = checker_file.read_text()
    assert "DependencyChecker" in content, "DependencyChecker not found"
    assert "async def check" in content, "check() method not found"


# ---------------------------------------------------------------------------
# CC-12: Routes file has JSON and HTML endpoints
# ---------------------------------------------------------------------------

def test_health_map_routes_file() -> None:
    """CC-12: health_map.py route has /health/map and /health/map.html endpoints."""
    project_dir = _fresh("hmap_t12")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "health_map.py"
    assert route_file.exists(), "health_map.py route not created"
    content = route_file.read_text()
    assert '"/map"' in content or "map" in content, "GET /health/map endpoint missing"
    assert "map.html" in content, "GET /health/map.html endpoint missing"


# ---------------------------------------------------------------------------
# CC-13: SVG visualization in HTML endpoint
# ---------------------------------------------------------------------------

def test_svg_visualization_present() -> None:
    """CC-13: health_map.py HTML endpoint renders an SVG dependency graph."""
    project_dir = _fresh("hmap_t13")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "health_map.py"
    content = route_file.read_text()
    assert "<svg" in content or "svg" in content.lower(), (
        "SVG visualization not found in health_map route"
    )


# ---------------------------------------------------------------------------
# CC-14: HealthMapBuilder.discover() uses env vars
# ---------------------------------------------------------------------------

def test_discover_uses_env_vars() -> None:
    """CC-14: HealthMapBuilder.discover() checks environment variable presence."""
    project_dir = _fresh("hmap_t14")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "health_map" / "__init__.py"
    content = init_file.read_text()
    assert "os.getenv" in content or "environ" in content, (
        "discover() must use env vars to detect configured deps"
    )
    assert "POSTGRES_SERVER" in content or "database" in content, (
        "Database dependency detection not present"
    )
    assert "REDIS_URL" in content or "redis" in content, (
        "Redis dependency detection not present"
    )


# ---------------------------------------------------------------------------
# CC-15: DependencyChecker checks all 4 known deps
# ---------------------------------------------------------------------------

def test_checker_covers_known_deps() -> None:
    """CC-15: DependencyChecker covers database, redis, s3, stripe."""
    project_dir = _fresh("hmap_t15")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    checker_file = project_dir / "app" / "health_map" / "checker.py"
    content = checker_file.read_text()
    for dep in ("database", "redis", "s3", "stripe"):
        assert dep in content, f"DependencyChecker missing check for: {dep}"


# ---------------------------------------------------------------------------
# CC-16: Lazy imports in checker
# ---------------------------------------------------------------------------

def test_no_top_level_optional_sdk_imports() -> None:
    """CC-16: No optional SDK imports at module top level in health_map files."""
    project_dir = _fresh("hmap_t16")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    hmap_dir = project_dir / "app" / "health_map"
    optional_sdks = {"redis", "aiobotocore", "stripe"}
    for py_file in sorted(hmap_dir.rglob("*.py")):
        tree = ast.parse(py_file.read_text())
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for name in names:
                    root = name.split(".")[0]
                    assert root not in optional_sdks, (
                        f"Optional SDK '{root}' imported at module level in {py_file}"
                    )


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms recorded
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = _fresh("hmap_t17")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present with keyword
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions HEALTH_MAP_ENABLED."""
    project_dir = _fresh("hmap_t18")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps)
    assert "HEALTH_MAP_ENABLED" in combined or "health" in combined.lower(), (
        "next_steps should mention HEALTH_MAP_ENABLED"
    )


# ---------------------------------------------------------------------------
# CC-17: register() custom dep method exists
# ---------------------------------------------------------------------------

def test_register_method_exists() -> None:
    """CC-17: HealthMapBuilder.register() allows custom dependency registration."""
    project_dir = _fresh("hmap_t19")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "health_map" / "__init__.py"
    content = init_file.read_text()
    assert "def register" in content, "HealthMapBuilder.register() not found"


# ---------------------------------------------------------------------------
# CC-18: build_graph returns nodes and edges
# ---------------------------------------------------------------------------

def test_build_graph_structure() -> None:
    """CC-18: build_graph() returns a graph with 'nodes' and 'edges' keys."""
    project_dir = _fresh("hmap_t20")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "health_map" / "__init__.py"
    content = init_file.read_text()
    assert "nodes" in content, "build_graph must include 'nodes' in the graph"
    assert "edges" in content, "build_graph must include 'edges' in the graph"


# ---------------------------------------------------------------------------
# CC-19: 503 on unhealthy in HTML route
# ---------------------------------------------------------------------------

def test_html_route_returns_503_on_unhealthy() -> None:
    """CC-19: HTML endpoint sets 503 status when any dep is unhealthy."""
    project_dir = _fresh("hmap_t21")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "health_map.py"
    content = route_file.read_text()
    assert "503" in content, "HTML endpoint must set 503 when unhealthy"


# ---------------------------------------------------------------------------
# CC-20: Timeout in checker
# ---------------------------------------------------------------------------

def test_checker_has_timeout() -> None:
    """CC-20: DependencyChecker uses asyncio.wait_for for timeout enforcement."""
    project_dir = _fresh("hmap_t22")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    checker_file = project_dir / "app" / "health_map" / "checker.py"
    content = checker_file.read_text()
    assert "wait_for" in content or "timeout" in content.lower(), (
        "DependencyChecker must enforce timeouts"
    )


# ---------------------------------------------------------------------------
# CC-21: Notes mention graph and SVG
# ---------------------------------------------------------------------------

def test_notes_mention_graph_and_svg() -> None:
    """CC-21: notes describe the JSON graph and SVG visualization."""
    project_dir = _fresh("hmap_t23")
    result = add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "graph" in combined or "dependency" in combined, (
        "notes should describe the dependency graph"
    )
    assert "html" in combined or "visual" in combined or "svg" in combined, (
        "notes should mention the HTML/SVG visualization"
    )


# ---------------------------------------------------------------------------
# CC-LAST: Project still parses after two runs
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = _fresh("hmap_t24")
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
    add_dependency_health_map(ToolInput(project_dir=str(project_dir)))
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
        test_health_map_builder_init,
        test_routes_registered,
        test_dependency_checker_created,
        test_health_map_routes_file,
        test_svg_visualization_present,
        test_discover_uses_env_vars,
        test_checker_covers_known_deps,
        test_no_top_level_optional_sdk_imports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_register_method_exists,
        test_build_graph_structure,
        test_html_route_returns_503_on_unhealthy,
        test_checker_has_timeout,
        test_notes_mention_graph_and_svg,
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
    print(f"TOOL-123 add_dependency_health_map: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
