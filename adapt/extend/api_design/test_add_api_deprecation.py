"""Structural tests for TOOL-106 add_api_deprecation.

Generates real fixture projects via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/api_design/test_add_api_deprecation.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/api_design/test_add_api_deprecation.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.api_design.add_api_deprecation import add_api_deprecation
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
    project_dir = create_fixture_project(name="depr_t01")
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="depr_t02")
    r1 = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="depr_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 files (registry, middleware, reporter, route)."""
    project_dir = create_fixture_project(name="depr_t04")
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 1 file (config or routes init or main)."""
    project_dir = create_fixture_project(name="depr_t05")
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="depr_t06")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="depr_t07")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


def test_config_fields_patched() -> None:
    """CC-08: DEPRECATION_* fields exist inside the Settings class in config.py."""
    project_dir = create_fixture_project(name="depr_t08")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "DEPRECATION_WARN_DAYS_BEFORE_SUNSET" in content, (
        "Config field DEPRECATION_WARN_DAYS_BEFORE_SUNSET not found in config.py"
    )
    for line in content.splitlines():
        if "DEPRECATION_WARN_DAYS_BEFORE_SUNSET" in line:
            assert line.startswith("    "), (
                f"DEPRECATION_WARN_DAYS_BEFORE_SUNSET not inside class body: {line!r}"
            )
            break


def test_routes_registered() -> None:
    """CC-10: Deprecation router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="depr_t09")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "deprecation" in content.lower(), "Deprecation router not registered in routes __init__"


# ---------------------------------------------------------------------------
# Category C — Domain-specific tests (CC-11+)
# ---------------------------------------------------------------------------

def test_deprecation_registry_created() -> None:
    """CC-11: app/deprecation/__init__.py exists with DeprecationRegistry."""
    project_dir = create_fixture_project(name="depr_t10")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "deprecation" / "__init__.py"
    assert registry_file.exists(), "app/deprecation/__init__.py not created"
    content = registry_file.read_text()
    assert "DeprecationRegistry" in content, "DeprecationRegistry not found"
    assert "DeprecationEntry" in content, "DeprecationEntry not found"


def test_deprecated_decorator_created() -> None:
    """CC-12: @deprecated decorator is exported from app/deprecation/__init__.py."""
    project_dir = create_fixture_project(name="depr_t11")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "deprecation" / "__init__.py"
    content = registry_file.read_text()
    assert "def deprecated(" in content, "@deprecated decorator function not found"
    assert "sunset" in content, "@deprecated decorator missing 'sunset' parameter"
    assert "replacement" in content, "@deprecated decorator missing 'replacement' parameter"


def test_deprecation_middleware_created() -> None:
    """CC-13: app/deprecation/middleware.py exists with DeprecationMiddleware."""
    project_dir = create_fixture_project(name="depr_t12")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    middleware = project_dir / "app" / "deprecation" / "middleware.py"
    assert middleware.exists(), "app/deprecation/middleware.py not created"
    content = middleware.read_text()
    assert "DeprecationMiddleware" in content, "DeprecationMiddleware not found"
    assert "Sunset" in content, "Sunset header not added in middleware"
    assert "Deprecation" in content, "Deprecation header not added in middleware"


def test_rfc_8594_sunset_header() -> None:
    """CC-14: Middleware adds RFC 8594 Sunset header."""
    project_dir = create_fixture_project(name="depr_t13")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    middleware = project_dir / "app" / "deprecation" / "middleware.py"
    content = middleware.read_text()
    assert '"Sunset"' in content, "Middleware must add 'Sunset' header (RFC 8594)"
    assert '"Deprecation"' in content, "Middleware must add 'Deprecation' header"
    assert "successor-version" in content, "Middleware must add Link rel=successor-version"


def test_deprecation_reporter_created() -> None:
    """CC-15: app/deprecation/reporter.py exists with DeprecationReporter."""
    project_dir = create_fixture_project(name="depr_t14")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    reporter = project_dir / "app" / "deprecation" / "reporter.py"
    assert reporter.exists(), "app/deprecation/reporter.py not created"
    content = reporter.read_text()
    assert "DeprecationReporter" in content, "DeprecationReporter not found"
    assert "record" in content, "DeprecationReporter.record() not found"
    assert "usage_report" in content, "DeprecationReporter.usage_report() not found"


def test_deprecations_listing_route_created() -> None:
    """CC-16: app/api/routes/deprecation.py exists with GET /deprecations route."""
    project_dir = create_fixture_project(name="depr_t15")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "deprecation.py"
    assert route_file.exists(), "app/api/routes/deprecation.py not created"
    content = route_file.read_text()
    assert "/deprecations" in content, "GET /deprecations route not found in route file"


def test_singleton_registry_exported() -> None:
    """CC-17: Module-level 'registry' singleton is exported from app/deprecation/__init__.py."""
    project_dir = create_fixture_project(name="depr_t16")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "deprecation" / "__init__.py"
    content = registry_file.read_text()
    assert "registry = DeprecationRegistry()" in content, (
        "Module-level 'registry' singleton not found"
    )


def test_days_until_sunset_property() -> None:
    """CC-18: DeprecationEntry has days_until_sunset property."""
    project_dir = create_fixture_project(name="depr_t17")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    registry_file = project_dir / "app" / "deprecation" / "__init__.py"
    content = registry_file.read_text()
    assert "days_until_sunset" in content, "DeprecationEntry missing days_until_sunset property"


def test_no_hardcoded_secrets() -> None:
    """CC-19: No hardcoded secrets in generated templates."""
    project_dir = create_fixture_project(name="depr_t18")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    deprecation_dir = project_dir / "app" / "deprecation"
    for py_file in sorted(deprecation_dir.rglob("*.py")):
        content = py_file.read_text()
        for bad in ('password="', 'secret="', 'api_key="'):
            assert bad not in content, (
                f"Potential hardcoded secret in {py_file.name}: {bad}"
            )


def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="depr_t19")
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps mentions @deprecated decorator."""
    project_dir = create_fixture_project(name="depr_t20")
    result = add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps should not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "deprecated" in combined, "next_steps should mention @deprecated"


def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="depr_t21")
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    add_api_deprecation(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.api_design.add_api_deprecation import MCP_TOOL
    assert MCP_TOOL["entry"] == "add_api_deprecation", (
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
        test_deprecation_registry_created,
        test_deprecated_decorator_created,
        test_deprecation_middleware_created,
        test_rfc_8594_sunset_header,
        test_deprecation_reporter_created,
        test_deprecations_listing_route_created,
        test_singleton_registry_exported,
        test_days_until_sunset_property,
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
    print(f"TOOL-106 add_api_deprecation: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
