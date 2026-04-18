"""Tests for TOOL-077 add_data_import.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the MEGA_BRIEFING spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_data_import.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_data_import.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_import import add_data_import
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
    project_dir = create_fixture_project(name="imp_t01_success")
    result = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


# ---------------------------------------------------------------------------
# CC-02: idempotency
# ---------------------------------------------------------------------------

def test_idempotent() -> None:
    """CC-02: Second run returns status='no_op' with no files created or modified."""
    project_dir = create_fixture_project(name="imp_t02_idempotent")
    r1 = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


# ---------------------------------------------------------------------------
# CC-03: dry_run
# ---------------------------------------------------------------------------

def test_dry_run() -> None:
    """CC-03: dry_run=True returns success but writes nothing to disk."""
    project_dir = create_fixture_project(name="imp_t03_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_data_import(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


# ---------------------------------------------------------------------------
# CC-04: files_created
# ---------------------------------------------------------------------------

def test_files_created_count() -> None:
    """CC-04: At least 7 files created and all exist on disk."""
    project_dir = create_fixture_project(name="imp_t04_created_count")
    result = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, f"Expected >=7 files, got {len(result.files_created)}"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-05: files_modified
# ---------------------------------------------------------------------------

def test_files_modified_count() -> None:
    """CC-05: At least 1 file modified and all exist on disk."""
    project_dir = create_fixture_project(name="imp_t05_modified_count")
    result = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_modified) >= 1, "Expected at least 1 modified file"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


# ---------------------------------------------------------------------------
# CC-06: all .py files parse
# ---------------------------------------------------------------------------

def test_all_py_parse() -> None:
    """CC-06: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="imp_t06_parse_all")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# CC-07: no function over 50 LOC
# ---------------------------------------------------------------------------

def test_no_function_over_50_loc() -> None:
    """CC-07: No generated function exceeds 50 lines of code."""
    project_dir = create_fixture_project(name="imp_t07_func_loc")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    violations: list[str] = []
    for py_file in _all_py_files(project_dir):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loc = (node.end_lineno or node.lineno) - node.lineno + 1
                if loc > 50:
                    violations.append(f"{py_file}:{node.name} ({loc} LOC)")
    assert not violations, "Functions exceeding 50 LOC:\n" + "\n".join(violations)


# ---------------------------------------------------------------------------
# CC-08: config fields patched
# ---------------------------------------------------------------------------

def test_config_fields_patched() -> None:
    """CC-08: IMPORT_MAX_FILE_SIZE_MB and IMPORT_BATCH_SIZE appear in config.py."""
    project_dir = create_fixture_project(name="imp_t08_config")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    config_file = project_dir / "app" / "core" / "config.py"
    content = config_file.read_text()
    assert "IMPORT_MAX_FILE_SIZE_MB" in content, "IMPORT_MAX_FILE_SIZE_MB not in config"
    assert "IMPORT_BATCH_SIZE" in content, "IMPORT_BATCH_SIZE not in config"
    for line in content.splitlines():
        if "IMPORT_MAX_FILE_SIZE_MB" in line or "IMPORT_BATCH_SIZE" in line:
            assert line.startswith("    "), f"Config field not 4-space indented: {line!r}"


# ---------------------------------------------------------------------------
# CC-09: ImportJob in models/__init__.py
# ---------------------------------------------------------------------------

def test_models_init_patched() -> None:
    """CC-09: ImportJob is imported in app/models/__init__.py."""
    project_dir = create_fixture_project(name="imp_t09_models_init")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    models_init = project_dir / "app" / "models" / "__init__.py"
    assert "ImportJob" in models_init.read_text(), "ImportJob not registered in models/__init__.py"


# ---------------------------------------------------------------------------
# CC-10: routes registered
# ---------------------------------------------------------------------------

def test_routes_registered() -> None:
    """CC-10: imports_router is registered in app/routes/__init__.py."""
    project_dir = create_fixture_project(name="imp_t10_routes_init")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    routes_init = project_dir / "app" / "routes" / "__init__.py"
    if routes_init.exists():
        content = routes_init.read_text()
        assert "imports_router" in content or "imports" in content, \
            "imports router not registered in routes/__init__.py"


# ---------------------------------------------------------------------------
# CC-11+: domain-specific tests
# ---------------------------------------------------------------------------

def test_import_job_model_created() -> None:
    """Domain: app/models/import_job.py exists with ImportJob class."""
    project_dir = create_fixture_project(name="imp_t11_model")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "import_job.py"
    assert model_file.exists(), "import_job.py not created"
    content = model_file.read_text()
    assert "class ImportJob" in content, "ImportJob class missing"
    assert "status" in content, "status field missing"
    assert "file_name" in content, "file_name field missing"
    assert "total_rows" in content, "total_rows field missing"
    assert "processed" in content, "processed field missing"
    assert "failed" in content, "failed field missing"
    assert "error_report_url" in content, "error_report_url field missing"


def test_import_processor_created() -> None:
    """Domain: app/imports/processor.py exists with ImportProcessor class."""
    project_dir = create_fixture_project(name="imp_t12_processor")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    proc_file = project_dir / "app" / "imports" / "processor.py"
    assert proc_file.exists(), "processor.py not created"
    content = proc_file.read_text()
    assert "class ImportProcessor" in content, "ImportProcessor class missing"
    assert "def parse_csv" in content, "parse_csv method missing"
    assert "def parse_excel" in content, "parse_excel method missing"
    assert "def validate_rows" in content, "validate_rows method missing"
    assert "async def process_batch" in content, "process_batch method missing"


def test_openpyxl_lazy_import() -> None:
    """Domain: openpyxl is imported lazily inside parse_excel body, not at module top."""
    project_dir = create_fixture_project(name="imp_t13_lazy_openpyxl")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    proc_file = project_dir / "app" / "imports" / "processor.py"
    tree = ast.parse(proc_file.read_text())
    # openpyxl must NOT appear in module-level imports
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            src = ast.unparse(node)
            assert "openpyxl" not in src, f"openpyxl must not be at module level: {src}"
    # openpyxl MUST appear inside a function body
    found_lazy = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        if "openpyxl" in alias.name:
                            found_lazy = True
    assert found_lazy, "openpyxl must be imported lazily inside a function body"


def test_row_validator_created() -> None:
    """Domain: app/imports/validators.py exists with RowValidator class."""
    project_dir = create_fixture_project(name="imp_t14_validator")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    val_file = project_dir / "app" / "imports" / "validators.py"
    assert val_file.exists(), "validators.py not created"
    content = val_file.read_text()
    assert "class RowValidator" in content, "RowValidator class missing"
    assert "required_fields" in content, "required_fields attribute missing"
    assert "def validate" in content, "validate method missing"


def test_upload_route_exists() -> None:
    """Domain: POST /imports/upload endpoint exists in routes/imports.py."""
    project_dir = create_fixture_project(name="imp_t15_upload_route")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "imports.py"
    assert routes_file.exists(), "imports.py routes file not created"
    content = routes_file.read_text()
    assert '"/upload"' in content, "upload route not found"
    assert "UploadFile" in content, "UploadFile not used in upload route"


def test_status_route_exists() -> None:
    """Domain: GET /imports/{id}/status endpoint exists."""
    project_dir = create_fixture_project(name="imp_t16_status_route")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "imports.py"
    content = routes_file.read_text()
    assert "status" in content, "status route not found"
    assert "job_id" in content, "job_id path parameter not found"


def test_errors_route_exists() -> None:
    """Domain: GET /imports/{id}/errors endpoint exists."""
    project_dir = create_fixture_project(name="imp_t17_errors_route")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "imports.py"
    content = routes_file.read_text()
    assert "errors" in content, "errors route not found"


def test_migration_created() -> None:
    """Domain: Alembic migration for import_jobs table is created."""
    project_dir = create_fixture_project(name="imp_t18_migration")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*import_jobs*"))
    assert len(migration_files) >= 1, "No import_jobs migration created"


def test_migration_has_upgrade_downgrade() -> None:
    """Domain: Migration file has both upgrade() and downgrade()."""
    project_dir = create_fixture_project(name="imp_t19_mig_updown")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*import_jobs*"))
    assert migration_files, "No import_jobs migration found"
    content = migration_files[0].read_text()
    assert "def upgrade" in content, "upgrade() missing from migration"
    assert "def downgrade" in content, "downgrade() missing from migration"
    assert "import_jobs" in content, "import_jobs table not referenced in migration"


def test_crud_create_and_update_functions() -> None:
    """Domain: CRUD file has create_import_job and update_import_job_progress."""
    project_dir = create_fixture_project(name="imp_t20_crud")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "import_job.py"
    assert crud_file.exists(), "crud/import_job.py not created"
    content = crud_file.read_text()
    assert "async def create_import_job" in content, "create_import_job missing"
    assert "async def update_import_job_progress" in content, "update_import_job_progress missing"
    assert "async def mark_import_job_done" in content, "mark_import_job_done missing"
    assert "async def fail_import_job" in content, "fail_import_job missing"


def test_schema_has_import_job_status() -> None:
    """Domain: app/schemas/import_job.py has ImportJobStatus with from_attributes."""
    project_dir = create_fixture_project(name="imp_t21_schema")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "import_job.py"
    assert schema_file.exists(), "schemas/import_job.py not created"
    content = schema_file.read_text()
    assert "ImportJobStatus" in content, "ImportJobStatus schema missing"
    assert "from_attributes=True" in content, "ConfigDict(from_attributes=True) missing"


def test_imports_package_init_exports() -> None:
    """Domain: app/imports/__init__.py exports ImportProcessor and RowValidator."""
    project_dir = create_fixture_project(name="imp_t22_pkg_init")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    init_file = project_dir / "app" / "imports" / "__init__.py"
    assert init_file.exists(), "app/imports/__init__.py not created"
    content = init_file.read_text()
    assert "ImportProcessor" in content, "ImportProcessor not exported from package"
    assert "RowValidator" in content, "RowValidator not exported from package"


# ---------------------------------------------------------------------------
# CC-N-1: execution time
# ---------------------------------------------------------------------------

def test_execution_time_recorded() -> None:
    """CC-N-1: execution_time_ms is a positive integer after a successful run."""
    project_dir = create_fixture_project(name="imp_t23_timing")
    result = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# CC-N: next_steps
# ---------------------------------------------------------------------------

def test_next_steps_present() -> None:
    """CC-N: next_steps must not be empty on success and mention alembic."""
    project_dir = create_fixture_project(name="imp_t24_next_steps")
    result = add_data_import(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# CC-LAST: idempotent project still parses
# ---------------------------------------------------------------------------

def test_idempotent_project_still_parses() -> None:
    """CC-LAST: After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="imp_t25_idem_parse")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    add_data_import(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


# ---------------------------------------------------------------------------
# Additional structural tests
# ---------------------------------------------------------------------------

def test_error_return_on_invalid_dir() -> None:
    """Tool returns error status when project_dir does not exist."""
    result = add_data_import(ToolInput(project_dir="/nonexistent/path/xyz"))
    assert result.status == "error"
    assert result.error is not None
    assert result.execution_time_ms > 0


def test_dry_run_execution_time_recorded() -> None:
    """execution_time_ms is positive even on dry_run returns."""
    project_dir = create_fixture_project(name="imp_t27_dry_timing")
    result = add_data_import(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.execution_time_ms > 0, "execution_time_ms must be positive on dry_run"


def test_import_job_model_uses_uuid_pk() -> None:
    """Domain: ImportJob primary key is a UUID column."""
    project_dir = create_fixture_project(name="imp_t28_uuid_pk")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "import_job.py"
    content = model_file.read_text()
    assert "Uuid" in content or "uuid" in content.lower(), "UUID PK not found in ImportJob"
    assert "primary_key=True" in content, "primary_key=True not set on ImportJob.id"


def test_process_import_job_function_exists() -> None:
    """Domain: process_import_job async function exists in processor.py."""
    project_dir = create_fixture_project(name="imp_t29_process_fn")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    proc_file = project_dir / "app" / "imports" / "processor.py"
    content = proc_file.read_text()
    assert "async def process_import_job" in content, "process_import_job function missing"


def test_upload_route_checks_file_extension() -> None:
    """Domain: Upload route validates file extension against allowed set."""
    project_dir = create_fixture_project(name="imp_t30_ext_check")
    add_data_import(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "imports.py"
    content = routes_file.read_text()
    assert ".csv" in content or "csv" in content, "CSV extension not validated"
    assert ".xlsx" in content or "xlsx" in content, "XLSX extension not validated"


def test_mcp_tool_entry_matches_function() -> None:
    """INV-10: MCP_TOOL['entry'] must match the actual function name."""
    from adapt.extend.crud_data.add_data_import import MCP_TOOL, add_data_import as fn
    assert MCP_TOOL["entry"] == fn.__name__, (
        f"MCP_TOOL entry={MCP_TOOL['entry']!r} != function name={fn.__name__!r}"
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
        test_models_init_patched,
        test_routes_registered,
        test_import_job_model_created,
        test_import_processor_created,
        test_openpyxl_lazy_import,
        test_row_validator_created,
        test_upload_route_exists,
        test_status_route_exists,
        test_errors_route_exists,
        test_migration_created,
        test_migration_has_upgrade_downgrade,
        test_crud_create_and_update_functions,
        test_schema_has_import_job_status,
        test_imports_package_init_exports,
        test_execution_time_recorded,
        test_next_steps_present,
        test_idempotent_project_still_parses,
        test_error_return_on_invalid_dir,
        test_dry_run_execution_time_recorded,
        test_import_job_model_uses_uuid_pk,
        test_process_import_job_function_exists,
        test_upload_route_checks_file_extension,
        test_mcp_tool_entry_matches_function,
    ]

    passed = 0
    failed = 0
    errors: list[str] = []

    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            errors.append(f"{t.__name__}: {exc}")
            failed += 1

    print(f"\n{passed}/{passed + failed} passed")
    if failed:
        sys.exit(1)
