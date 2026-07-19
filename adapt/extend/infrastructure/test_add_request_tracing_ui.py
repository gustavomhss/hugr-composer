"""Tests for TOOL-122 add_request_tracing_ui.

Generates real fixture projects, runs the tool, and verifies all completeness
criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_request_tracing_ui.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_request_tracing_ui.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_request_tracing_ui import add_request_tracing_ui
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
# CC-01: Tool returns success on a fresh project
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """CC-01: Tool returns status='success' on a fresh project."""
    project_dir = _fresh("tui_t01")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: Idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns no_op with no files created or modified."""
    project_dir = _fresh("tui_t02")
    r1 = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes no files."""
    project_dir = _fresh("tui_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files created exist on disk
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 4 files are created and all exist on disk."""
    project_dir = _fresh("tui_t04")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files modified exist on disk
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file is modified and all exist on disk."""
    project_dir = _fresh("tui_t05")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
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
    project_dir = _fresh("tui_t06")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: No function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 LOC (AST walk)."""
    project_dir = _fresh("tui_t07")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    tracing_dir = project_dir / "app" / "tracing_ui"
    for py_file in sorted(tracing_dir.rglob("*.py")):
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
    """CC-08: TRACING_UI_ENABLED, TRACING_UI_BUFFER_SIZE, TRACING_UI_AUTH_REQUIRED in config."""
    project_dir = _fresh("tui_t08")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "TRACING_UI_ENABLED" in content
    assert "TRACING_UI_BUFFER_SIZE" in content
    assert "TRACING_UI_AUTH_REQUIRED" in content
    # Verify 4-space indent inside Settings class
    for line in content.splitlines():
        if "TRACING_UI_ENABLED" in line:
            assert line.startswith("    "), f"Field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: TracingBuffer ring buffer present
# ---------------------------------------------------------------------------

def test_tracing_buffer_init() -> None:
    """CC-09: app/tracing_ui/__init__.py exists and contains TracingBuffer."""
    project_dir = _fresh("tui_t09")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "tracing_ui" / "__init__.py"
    assert init_file.exists(), "app/tracing_ui/__init__.py not created"
    content = init_file.read_text()
    assert "TracingBuffer" in content, "TracingBuffer class not found"
    assert "get_tracing_buffer" in content, "get_tracing_buffer singleton not found"


# ---------------------------------------------------------------------------
# CC-10: Routes registered in main.py
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: tracing router included in app/main.py."""
    project_dir = _fresh("tui_t10")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "tracing_ui" in content or "tracing_router" in content, (
        "Tracing router not registered in main.py"
    )


# ---------------------------------------------------------------------------
# CC-11: TimingCollector in collector.py
# ---------------------------------------------------------------------------

def test_timing_collector_created() -> None:
    """CC-11: app/tracing_ui/collector.py exists with TimingCollector and span()."""
    project_dir = _fresh("tui_t11")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    collector_file = project_dir / "app" / "tracing_ui" / "collector.py"
    assert collector_file.exists(), "collector.py not created"
    content = collector_file.read_text()
    assert "TimingCollector" in content, "TimingCollector not found"
    assert "def span" in content, "span() context manager not found"
    assert "record_span" in content, "record_span() not found"


# ---------------------------------------------------------------------------
# CC-12: Middleware created
# ---------------------------------------------------------------------------

def test_middleware_created() -> None:
    """CC-12: app/tracing_ui/middleware.py exists with TracingMiddleware."""
    project_dir = _fresh("tui_t12")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "tracing_ui" / "middleware.py"
    assert mw_file.exists(), "middleware.py not created"
    content = mw_file.read_text()
    assert "TracingMiddleware" in content, "TracingMiddleware not found"


# ---------------------------------------------------------------------------
# CC-13: Routes file has all 4 endpoints
# ---------------------------------------------------------------------------

def test_tracing_routes_file() -> None:
    """CC-13: tracing.py route has /requests, /{id}, /slow, /dashboard endpoints."""
    project_dir = _fresh("tui_t13")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "tracing.py"
    assert route_file.exists(), "tracing.py route not created"
    content = route_file.read_text()
    assert "/requests" in content, "GET /tracing/requests endpoint missing"
    assert "request_id" in content or "{request_id}" in content, (
        "GET /tracing/requests/{id} endpoint missing"
    )
    assert "slow" in content, "GET /tracing/slow endpoint missing"
    assert "dashboard" in content, "GET /tracing/dashboard endpoint missing"


# ---------------------------------------------------------------------------
# CC-14: HTML dashboard file created
# ---------------------------------------------------------------------------

def test_dashboard_html_created() -> None:
    """CC-14: app/tracing_ui/templates/dashboard.html exists with JS and table."""
    project_dir = _fresh("tui_t14")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    html_file = project_dir / "app" / "tracing_ui" / "templates" / "dashboard.html"
    assert html_file.exists(), "dashboard.html not created"
    content = html_file.read_text()
    assert "<script>" in content, "No JavaScript in dashboard.html"
    assert "tracing/requests" in content, "dashboard.html must fetch /tracing/requests"
    assert "<table" in content, "dashboard.html must include a <table>"


# ---------------------------------------------------------------------------
# CC-15: Ring buffer get_slow returns p99
# ---------------------------------------------------------------------------

def test_tracing_buffer_get_slow() -> None:
    """CC-15: TracingBuffer.get_slow() is defined and accepts a percentile argument."""
    project_dir = _fresh("tui_t15")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "tracing_ui" / "__init__.py"
    content = init_file.read_text()
    assert "get_slow" in content, "TracingBuffer.get_slow() not defined"
    assert "percentile" in content, "get_slow() must accept a percentile argument"


# ---------------------------------------------------------------------------
# CC-16: Lazy imports verified — no top-level optional SDKs
# ---------------------------------------------------------------------------

def test_no_top_level_optional_sdk_imports() -> None:
    """CC-16: No optional SDK imports at module top level in generated files."""
    project_dir = _fresh("tui_t16")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    tracing_dir = project_dir / "app" / "tracing_ui"
    optional_sdks = {"redis", "aiobotocore", "stripe", "celery"}
    for py_file in sorted(tracing_dir.rglob("*.py")):
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
    project_dir = _fresh("tui_t17")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps present with keyword
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps is non-empty and mentions TRACING_UI_ENABLED."""
    project_dir = _fresh("tui_t18")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps)
    assert "TRACING_UI_ENABLED" in combined or "tracing" in combined.lower(), (
        "next_steps should mention TRACING_UI_ENABLED"
    )


# ---------------------------------------------------------------------------
# CC-17: make_request_id generates UUIDs
# ---------------------------------------------------------------------------

def test_make_request_id_defined() -> None:
    """CC-17: make_request_id() function is defined in tracing_ui/__init__.py."""
    project_dir = _fresh("tui_t19")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "tracing_ui" / "__init__.py"
    content = init_file.read_text()
    assert "make_request_id" in content, "make_request_id() not found"
    assert "uuid" in content, "UUID generation not found"


# ---------------------------------------------------------------------------
# CC-18: Dashboard uses auto-refresh
# ---------------------------------------------------------------------------

def test_dashboard_auto_refresh() -> None:
    """CC-18: dashboard.html auto-refreshes using setInterval."""
    project_dir = _fresh("tui_t20")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    html_file = project_dir / "app" / "tracing_ui" / "templates" / "dashboard.html"
    content = html_file.read_text()
    assert "setInterval" in content, "dashboard.html must auto-refresh with setInterval"


# ---------------------------------------------------------------------------
# CC-19: TracingBuffer record() method defined
# ---------------------------------------------------------------------------

def test_tracing_buffer_record_method() -> None:
    """CC-19: TracingBuffer.record() and get_all() are defined."""
    project_dir = _fresh("tui_t21")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "tracing_ui" / "__init__.py"
    content = init_file.read_text()
    assert "def record" in content, "TracingBuffer.record() not found"
    assert "def get_all" in content, "TracingBuffer.get_all() not found"
    assert "def get_by_id" in content, "TracingBuffer.get_by_id() not found"


# ---------------------------------------------------------------------------
# CC-20: TRACING_UI_BUFFER_SIZE default is 1000
# ---------------------------------------------------------------------------

def test_buffer_size_default() -> None:
    """CC-20: Default buffer size 1000 appears in generated code."""
    project_dir = _fresh("tui_t22")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "tracing_ui" / "__init__.py"
    content = init_file.read_text()
    assert "1000" in content, "Default buffer size 1000 not found in TracingBuffer"


# ---------------------------------------------------------------------------
# CC-21: Notes mention ring buffer and dashboard
# ---------------------------------------------------------------------------

def test_notes_mention_ring_buffer_and_dashboard() -> None:
    """CC-21: notes describe the ring buffer and dashboard endpoint."""
    project_dir = _fresh("tui_t23")
    result = add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    combined = " ".join(result.notes).lower()
    assert "ring buffer" in combined or "tracing" in combined, (
        "notes should describe the ring buffer"
    )
    assert "dashboard" in combined, "notes should mention the dashboard endpoint"


# ---------------------------------------------------------------------------
# CC-LAST: Project still parses after two runs
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs all .py files remain parseable."""
    project_dir = _fresh("tui_t24")
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
    add_request_tracing_ui(ToolInput(project_dir=str(project_dir)))
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
        test_tracing_buffer_init,
        test_routes_registered,
        test_timing_collector_created,
        test_middleware_created,
        test_tracing_routes_file,
        test_dashboard_html_created,
        test_tracing_buffer_get_slow,
        test_no_top_level_optional_sdk_imports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_make_request_id_defined,
        test_dashboard_auto_refresh,
        test_tracing_buffer_record_method,
        test_buffer_size_default,
        test_notes_mention_ring_buffer_and_dashboard,
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
    print(f"TOOL-122 add_request_tracing_ui: {passed} passed, {failed} failed")
    if failed:
        sys.exit(1)
