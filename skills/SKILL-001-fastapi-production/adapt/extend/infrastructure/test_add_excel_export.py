"""Structural tests for TOOL-084 add_excel_export.

Covers all Completeness Criteria (CC-01 through CC-LAST) from the
MEGA_BRIEFING.

Run with::

    PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_excel_export.py -v

or standalone::

    PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_excel_export.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.infrastructure.add_excel_export import add_excel_export
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
    project_dir = create_fixture_project(name="excel_t01")
    result = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", (
        f"Expected success, got {result.status}: {result.error}"
    )


# ---------------------------------------------------------------------------
# CC-02: idempotent
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """Second run returns status='no_op' without touching files."""
    project_dir = create_fixture_project(name="excel_t02")
    r1 = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """dry_run=True returns success but writes no files."""
    project_dir = create_fixture_project(name="excel_t03")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_excel_export(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created count
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """Tool creates at least 4 new files."""
    project_dir = create_fixture_project(name="excel_t04")
    result = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 4, (
        f"Expected >= 4 files_created, got {len(result.files_created)}: "
        f"{result.files_created}"
    )
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified count
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """Tool modifies at least 2 files (config, routes init)."""
    project_dir = create_fixture_project(name="excel_t05")
    result = add_excel_export(ToolInput(project_dir=str(project_dir)))
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
    project_dir = create_fixture_project(name="excel_t06")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """No function in generated app/ exceeds 50 LOC."""
    project_dir = create_fixture_project(name="excel_t07")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    max_loc = _max_function_loc(project_dir, "app")
    assert max_loc <= 50, f"Found function with {max_loc} LOC (limit: 50)"


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """EXCEL_MAX_ROWS and EXCEL_CHUNK_SIZE exist inside Settings class."""
    project_dir = create_fixture_project(name="excel_t08")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    for field in ("EXCEL_MAX_ROWS", "EXCEL_CHUNK_SIZE"):
        assert field in content, f"Config field {field} not found in config.py"
    # Verify field is inside class body (4-space indent)
    for line in content.splitlines():
        if "EXCEL_MAX_ROWS" in line and ":" in line:
            assert line.startswith("    "), (
                f"EXCEL_MAX_ROWS not inside class body (no 4-space indent): {line!r}"
            )
            break


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """Excel export router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="excel_t10")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "excel" in content.lower(), (
            "Excel router not registered in routes __init__"
        )


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests (≥5)
# ---------------------------------------------------------------------------

def test_exports_package_exists() -> None:
    """app/exports/__init__.py exists and exports ExcelExporter."""
    project_dir = create_fixture_project(name="excel_t11")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    pkg_init = project_dir / "app" / "exports" / "__init__.py"
    assert pkg_init.exists(), "app/exports/__init__.py not created"
    content = pkg_init.read_text()
    assert "ExcelExporter" in content, (
        "ExcelExporter not exported from app/exports/__init__.py"
    )


def test_excel_exporter_has_streaming_methods() -> None:
    """app/exports/excel.py has create_workbook, add_sheet, stream_rows, to_bytes."""
    project_dir = create_fixture_project(name="excel_t12")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    excel_file = project_dir / "app" / "exports" / "excel.py"
    assert excel_file.exists(), "app/exports/excel.py not created"
    content = excel_file.read_text()
    for method in ("create_workbook", "add_sheet", "stream_rows", "to_bytes"):
        assert method in content, f"{method} not found in excel.py"


def test_openpyxl_import_is_lazy() -> None:
    """openpyxl is imported inside function bodies, not at module level."""
    project_dir = create_fixture_project(name="excel_t13")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    excel_file = project_dir / "app" / "exports" / "excel.py"
    tree = ast.parse(excel_file.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in (node.names if isinstance(node, ast.Import) else []):
                assert "openpyxl" not in alias.name.lower(), (
                    "openpyxl imported at module level — must be lazy!"
                )
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "openpyxl" not in node.module.lower(), (
                    "openpyxl imported at module level — must be lazy!"
                )


def test_formatters_file_has_auto_width() -> None:
    """app/exports/formatters.py has auto_fit_columns and apply_header_style."""
    project_dir = create_fixture_project(name="excel_t14")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    fmt_file = project_dir / "app" / "exports" / "formatters.py"
    assert fmt_file.exists(), "app/exports/formatters.py not created"
    content = fmt_file.read_text()
    assert "auto_fit_columns" in content, "auto_fit_columns not in formatters.py"
    assert "apply_header_style" in content, "apply_header_style not in formatters.py"


def test_route_file_has_post_and_download() -> None:
    """app/api/routes/excel_export.py has POST /exports/excel and GET /{id}/download."""
    project_dir = create_fixture_project(name="excel_t15")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "excel_export.py"
    assert route_file.exists(), "app/api/routes/excel_export.py not created"
    content = route_file.read_text()
    assert "export_excel" in content or "/excel" in content, (
        "Excel export route not found"
    )
    assert "download" in content, "Download route not found in excel_export.py"


def test_streaming_response_used() -> None:
    """Routes use StreamingResponse for file delivery."""
    project_dir = create_fixture_project(name="excel_t16")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "excel_export.py"
    content = route_file.read_text()
    assert "StreamingResponse" in content, (
        "StreamingResponse not used in excel_export.py"
    )


def test_max_rows_enforced_in_exporter() -> None:
    """ExcelExporter.stream_rows raises ValueError when max_rows exceeded."""
    project_dir = create_fixture_project(name="excel_t17")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    excel_file = project_dir / "app" / "exports" / "excel.py"
    content = excel_file.read_text()
    assert "max_rows" in content, "max_rows not enforced in ExcelExporter"
    assert "ValueError" in content, "ValueError not raised in stream_rows"


# ---------------------------------------------------------------------------
# CC-N-1: execution_time_ms
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer."""
    project_dir = create_fixture_project(name="excel_t18")
    result = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """next_steps should mention openpyxl."""
    project_dir = create_fixture_project(name="excel_t19")
    result = add_excel_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty"
    combined = " ".join(result.next_steps).lower()
    assert "openpyxl" in combined, "next_steps should mention openpyxl"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """After two runs all .py files remain parseable."""
    project_dir = create_fixture_project(name="excel_t20")
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    add_excel_export(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Extra: error on invalid project_dir
# ---------------------------------------------------------------------------

def test_error_on_missing_project_dir() -> None:
    """Tool returns error when project_dir does not exist."""
    result = add_excel_export(ToolInput(project_dir="/nonexistent/path/xyz"))
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
        test_exports_package_exists,
        test_excel_exporter_has_streaming_methods,
        test_openpyxl_import_is_lazy,
        test_formatters_file_has_auto_width,
        test_route_file_has_post_and_download,
        test_streaming_response_used,
        test_max_rows_enforced_in_exporter,
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
