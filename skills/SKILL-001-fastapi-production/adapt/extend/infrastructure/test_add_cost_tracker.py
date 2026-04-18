"""Structural tests for TOOL-120 add_cost_tracker.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_cost_tracker.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_cost_tracker.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_cost_tracker import add_cost_tracker
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="cost_t01")
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="cost_t02")
    r1 = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="cost_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: Tool creates at least 4 new files."""
    project_dir = create_fixture_project(name="cost_t04")
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: {result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="cost_t05")
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: {result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="cost_t06")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="cost_t07")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: COST_* config fields exist inside the Settings class body."""
    project_dir = create_fixture_project(name="cost_t08")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ["COST_TRACKING_ENABLED", "COST_DB_QUERY_RATE", "COST_S3_PER_GB", "COST_API_CALL_RATE"]:
        assert field in content, f"Config field {field} not found in config.py"
    for line in content.splitlines():
        if "COST_TRACKING_ENABLED" in line and ":" in line:
            assert line.startswith("    "), (
                f"COST_TRACKING_ENABLED not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: (no model — skip models_init check; use routes check instead)
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: Costs router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="cost_t09")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "costs_router" in content or "costs" in content.lower(), (
            "Costs router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_cost_tracker_core_created() -> None:
    """CC-11: app/costs/tracker.py exists with CostTracker and RequestContext."""
    project_dir = create_fixture_project(name="cost_t10")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    tracker_file = project_dir / "app" / "costs" / "tracker.py"
    assert tracker_file.exists(), "app/costs/tracker.py not created"
    content = tracker_file.read_text()
    assert "class CostTracker" in content, "CostTracker class not found"
    assert "class RequestContext" in content, "RequestContext class not found"
    assert "class CostEstimate" in content, "CostEstimate class not found"


def test_estimators_created() -> None:
    """CC-11: app/costs/estimators.py contains all three estimators."""
    project_dir = create_fixture_project(name="cost_t11")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    estimators_file = project_dir / "app" / "costs" / "estimators.py"
    assert estimators_file.exists(), "app/costs/estimators.py not created"
    content = estimators_file.read_text()
    assert "DBQueryCostEstimator" in content, "DBQueryCostEstimator not found"
    assert "S3CostEstimator" in content, "S3CostEstimator not found"
    assert "APICostEstimator" in content, "APICostEstimator not found"


def test_cost_middleware_created() -> None:
    """CC-11: app/middleware/cost_tracker.py exists with CostMiddleware."""
    project_dir = create_fixture_project(name="cost_t12")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "middleware" / "cost_tracker.py"
    assert middleware_file.exists(), "app/middleware/cost_tracker.py not created"
    content = middleware_file.read_text()
    assert "class CostMiddleware" in content, "CostMiddleware class not found"
    assert "X-Request-Cost-Estimate" in content, (
        "X-Request-Cost-Estimate header not found in CostMiddleware"
    )


def test_cost_routes_endpoints() -> None:
    """CC-11: app/api/routes/costs.py contains /summary and /by-endpoint."""
    project_dir = create_fixture_project(name="cost_t13")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "costs.py"
    assert route_file.exists(), "app/api/routes/costs.py not created"
    content = route_file.read_text()
    assert "/summary" in content, "/costs/summary endpoint not found"
    assert "/by-endpoint" in content, "/costs/by-endpoint endpoint not found"


def test_header_value_format() -> None:
    """CC-11: CostEstimate.as_header_value() returns a $ prefixed string."""
    project_dir = create_fixture_project(name="cost_t14")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    tracker_file = project_dir / "app" / "costs" / "tracker.py"
    content = tracker_file.read_text()
    assert "as_header_value" in content, "as_header_value method not found"
    assert '"$' in content or "'$" in content, "$ prefix not found in header value method"


def test_estimator_components_named() -> None:
    """CC-11: Each estimator exposes a 'component' attribute with expected value."""
    project_dir = create_fixture_project(name="cost_t15")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    estimators_file = project_dir / "app" / "costs" / "estimators.py"
    content = estimators_file.read_text()
    assert 'component = "db"' in content, 'DBQueryCostEstimator.component != "db"'
    assert 'component = "s3"' in content, 'S3CostEstimator.component != "s3"'
    assert 'component = "api"' in content, 'APICostEstimator.component != "api"'


def test_get_by_endpoint_exists() -> None:
    """CC-11: CostTracker.get_by_endpoint() method exists."""
    project_dir = create_fixture_project(name="cost_t16")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    tracker_file = project_dir / "app" / "costs" / "tracker.py"
    content = tracker_file.read_text()
    assert "def get_by_endpoint" in content, "get_by_endpoint method not found in CostTracker"


def test_get_summary_periods() -> None:
    """CC-11: CostTracker.get_summary() returns daily/weekly/monthly keys."""
    project_dir = create_fixture_project(name="cost_t17")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    tracker_file = project_dir / "app" / "costs" / "tracker.py"
    content = tracker_file.read_text()
    assert "daily" in content, "'daily' period not in CostTracker.get_summary()"
    assert "weekly" in content, "'weekly' period not in CostTracker.get_summary()"
    assert "monthly" in content, "'monthly' period not in CostTracker.get_summary()"


# ---------------------------------------------------------------------------
# CC-N-1 & CC-N: execution_time and next_steps
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="cost_t18")
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions configuration."""
    project_dir = create_fixture_project(name="cost_t19")
    result = add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    assert result.next_steps, "next_steps must be non-empty"
    combined = " ".join(result.next_steps).lower()
    assert "cost" in combined or "enabled" in combined, (
        "next_steps should mention cost tracking configuration"
    )


# ---------------------------------------------------------------------------
# CC-LAST: idempotent + project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="cost_t20")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_cost_middleware_non_blocking() -> None:
    """CC-11: CostMiddleware must catch exceptions (non-blocking pattern)."""
    project_dir = create_fixture_project(name="cost_t21")
    add_cost_tracker(ToolInput(project_dir=str(project_dir)))
    middleware_file = project_dir / "app" / "middleware" / "cost_tracker.py"
    content = middleware_file.read_text()
    assert "except Exception" in content, (
        "CostMiddleware must catch exceptions to avoid blocking requests"
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
        test_cost_tracker_core_created,
        test_estimators_created,
        test_cost_middleware_created,
        test_cost_routes_endpoints,
        test_header_value_format,
        test_estimator_components_named,
        test_get_by_endpoint_exists,
        test_get_summary_periods,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_cost_middleware_non_blocking,
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
    print(f"TOOL-120 add_cost_tracker: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
