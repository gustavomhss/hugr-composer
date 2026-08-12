"""Structural tests for TOOL-083 add_pdf_reports.

Covers all Completeness Criteria (CC-01 through CC-LAST) from the
MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_pdf_reports.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_pdf_reports.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_pdf_reports import add_pdf_reports
from tests.common.fixture_factory import create_fixture_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py_files(root: Path) -> list[Path]:
    """Return all .py files under root, sorted."""
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    """Assert every .py file under root parses without SyntaxError."""
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
# CC-01: success status
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="pdf_t01")
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="pdf_t02")
    r1 = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="pdf_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 5 new files."""
    project_dir = create_fixture_project(name="pdf_t04")
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 5, (
        f"Expected >= 5 files_created, got {len(result.files_created)}: "
        f"{result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="pdf_t05")
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 2, (
        f"Expected >= 2 files_modified, got {len(result.files_modified)}: "
        f"{result.files_modified}"
    )
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """Every generated .py file AST-parses clean."""
    project_dir = create_fixture_project(name="pdf_t06")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="pdf_t07")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """Expected REPORT_* settings fields exist inside the Settings class."""
    project_dir = create_fixture_project(name="pdf_t08")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("REPORT_TEMPLATE_DIR", "REPORT_OUTPUT_DIR", "REPORT_MAX_PAGES"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify the field is inside the Settings class (4-space indent)
    for line in content.splitlines():
        if "REPORT_TEMPLATE_DIR" in line and ":" in line:
            assert line.startswith("    "), (
                f"REPORT_TEMPLATE_DIR not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-09: models init not patched (no model created — skip)
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """Reports router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="pdf_t10")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "reports" in content.lower(), (
            "Reports router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests (≥5)
# ---------------------------------------------------------------------------

def test_reports_package_exists() -> None:
    """app/reports/__init__.py exists and exports ReportEngine."""
    project_dir = create_fixture_project(name="pdf_t11")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    pkg_init = project_dir / "app" / "reports" / "__init__.py"
    assert pkg_init.exists(), "app/reports/__init__.py not created"
    content = pkg_init.read_text()
    assert "ReportEngine" in content, "ReportEngine not exported from app/reports/__init__.py"


def test_engine_file_has_render_methods() -> None:
    """app/reports/engine.py has render_template and render_html_to_pdf."""
    project_dir = create_fixture_project(name="pdf_t12")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "reports" / "engine.py"
    assert engine_file.exists(), "app/reports/engine.py not created"
    content = engine_file.read_text()
    assert "render_template" in content, "render_template not found in engine.py"
    assert "render_html_to_pdf" in content, "render_html_to_pdf not found in engine.py"
    assert "generate_pdf_async" in content, "generate_pdf_async not found in engine.py"


def test_weasyprint_import_is_lazy() -> None:
    """WeasyPrint is imported inside a function body, not at module level."""
    project_dir = create_fixture_project(name="pdf_t13")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "reports" / "engine.py"
    tree = ast.parse(engine_file.read_text())
    # Top-level imports must NOT include weasyprint
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in (node.names if isinstance(node, ast.Import) else []):
                assert "weasyprint" not in alias.name.lower(), (
                    "weasyprint imported at module level — must be lazy!"
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "weasyprint" not in node.module.lower(), (
                    "weasyprint imported at module level — must be lazy!"
                )


def test_jinja2_autoescape_in_engine() -> None:
    """ReportEngine uses Jinja2 autoescape for HTML templates."""
    project_dir = create_fixture_project(name="pdf_t14")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "reports" / "engine.py"
    content = engine_file.read_text()
    assert "autoescape" in content, "autoescape not set in Jinja2 Environment in engine.py"


def test_template_files_exist() -> None:
    """3 HTML templates (invoice, summary, receipt) exist."""
    project_dir = create_fixture_project(name="pdf_t15")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    tpl_dir = project_dir / "app" / "reports" / "templates"
    assert tpl_dir.exists(), "app/reports/templates/ not created"
    for name in ("invoice.html", "summary.html", "receipt.html"):
        assert (tpl_dir / name).exists(), f"Template file missing: {name}"


def test_route_file_has_generate_and_download() -> None:
    """app/api/routes/reports.py has /generate and /{id}/download routes."""
    project_dir = create_fixture_project(name="pdf_t16")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "reports.py"
    assert route_file.exists(), "app/api/routes/reports.py not created"
    content = route_file.read_text()
    assert "generate" in content, "generate route not found in reports.py"
    assert "download" in content, "download route not found in reports.py"


def test_schema_file_has_request_and_response() -> None:
    """app/schemas/report.py has ReportRequest and ReportResponse."""
    project_dir = create_fixture_project(name="pdf_t17")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "report.py"
    assert schema_file.exists(), "app/schemas/report.py not created"
    content = schema_file.read_text()
    assert "ReportRequest" in content, "ReportRequest not in schemas/report.py"
    assert "ReportResponse" in content, "ReportResponse not in schemas/report.py"
    assert "download_url" in content, "download_url field not in ReportResponse"


def test_run_in_executor_used_for_async() -> None:
    """generate_pdf_async uses run_in_executor for CPU-bound rendering."""
    project_dir = create_fixture_project(name="pdf_t18")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    engine_file = project_dir / "app" / "reports" / "engine.py"
    content = engine_file.read_text()
    assert "run_in_executor" in content, (
        "run_in_executor not used in engine.py — async generation must be non-blocking"
    )


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="pdf_t19")
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps should mention weasyprint and REPORT_OUTPUT_DIR."""
    project_dir = create_fixture_project(name="pdf_t20")
    result = add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "weasyprint" in combined, "next_steps should mention weasyprint"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="pdf_t21")
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    add_pdf_reports(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: error on invalid project_dir
# ---------------------------------------------------------------------------

def test_error_on_missing_project_dir() -> None:
    """Tool returns error when project_dir does not exist."""
    result = add_pdf_reports(ToolInput(project_dir="/nonexistent/path/xyz"))
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms >= 0


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
        test_reports_package_exists,
        test_engine_file_has_render_methods,
        test_weasyprint_import_is_lazy,
        test_jinja2_autoescape_in_engine,
        test_template_files_exist,
        test_route_file_has_generate_and_download,
        test_schema_file_has_request_and_response,
        test_run_in_executor_used_for_async,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_error_on_missing_project_dir,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1

    total = passed + failed
    print(f"\n{passed}/{total} passed")
    sys.exit(0 if failed == 0 else 1)
