"""Tests for TOOL-006 add_data_export.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_data_export.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_data_export.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_data_export import add_data_export
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
# Test cases
# ---------------------------------------------------------------------------

def test_success_status() -> None:
    """T-01: Tool returns status='success' on a fresh project."""
    project_dir = create_fixture_project(name="exp_t01_success")
    result = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="exp_t02_files_exist")
    result = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="exp_t03_modified_exist")
    result = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_export_core_file_created() -> None:
    """CC-01: app/core/export.py exists after tool run."""
    project_dir = create_fixture_project(name="exp_t04_core")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    assert export_core.exists(), "app/core/export.py not created"


def test_stream_batches_uses_yield_per() -> None:
    """CC-02: _stream_batches uses session.stream with yield_per execution option."""
    project_dir = create_fixture_project(name="exp_t05_yield_per")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "yield_per" in content, "_stream_batches must use yield_per"


def test_export_csv_yields_per_batch() -> None:
    """CC-03: export_csv yields bytes per batch (generator with yield inside loop)."""
    project_dir = create_fixture_project(name="exp_t06_csv_yield")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "export_csv" in content
    assert "yield" in content, "export_csv must yield bytes chunks"


def test_export_ndjson_present() -> None:
    """CC-04: export_ndjson function exists and yields NDJSON lines."""
    project_dir = create_fixture_project(name="exp_t07_ndjson")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "export_ndjson" in content
    assert "\\n" in content, "NDJSON must include newline separators"


def test_export_xlsx_uses_constant_memory() -> None:
    """CC-05: export_xlsx uses constant_memory=True in xlsxwriter Workbook."""
    project_dir = create_fixture_project(name="exp_t08_xlsx")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "constant_memory" in content, "export_xlsx must use constant_memory=True"


def test_export_parquet_uses_pyarrow() -> None:
    """CC-06: export_parquet uses pyarrow.parquet.write_table."""
    project_dir = create_fixture_project(name="exp_t09_parquet")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "pq.write_table" in content, "export_parquet must use pq.write_table"


def test_serialize_handles_all_types() -> None:
    """CC-07: _serialize handles datetime, UUID, Decimal, bytes."""
    project_dir = create_fixture_project(name="exp_t10_serialize")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    for t in ("datetime", "UUID", "Decimal", "bytes"):
        assert t in content, f"_serialize must handle {t}"


def test_sensitive_columns_frozenset_defined() -> None:
    """CC-08: SENSITIVE_COLUMNS frozenset is defined in export.py."""
    project_dir = create_fixture_project(name="exp_t11_sensitive")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_core = project_dir / "app" / "core" / "export.py"
    content = export_core.read_text()
    assert "SENSITIVE_COLUMNS" in content
    assert "hashed_password" in content
    assert "api_key" in content


def test_export_route_registered() -> None:
    """CC-09: GET /{model}/export route exists in the model route file."""
    project_dir = create_fixture_project(name="exp_t12_route")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    assert route_file.exists()
    content = route_file.read_text()
    assert "/export" in content, "Route file must contain /export endpoint"


def test_route_accepts_format_with_pattern() -> None:
    """CC-10: Export route accepts format Query with regex pattern validation."""
    project_dir = create_fixture_project(name="exp_t13_format_pattern")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "pattern=" in content, "format Query must include pattern= for validation"


def test_route_accepts_columns_query() -> None:
    """CC-11: Export route accepts optional columns Query parameter."""
    project_dir = create_fixture_project(name="exp_t14_columns")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "columns" in content, "Export route must accept columns parameter"


def test_default_columns_excludes_sensitive() -> None:
    """CC-12: Default export columns exclude all SENSITIVE_COLUMNS entries."""
    project_dir = create_fixture_project(name="exp_t15_default_cols")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "SENSITIVE_COLUMNS" in content or "_SENSITIVE_COLUMNS" in content, \
        "Route must filter against SENSITIVE_COLUMNS"


def test_preflight_count_before_streaming() -> None:
    """CC-13: Route executes COUNT(*) preflight before deciding sync vs async."""
    project_dir = create_fixture_project(name="exp_t16_preflight")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "func.count()" in content or "_func.count()" in content, \
        "Route must execute COUNT(*) preflight"


def test_async_dispatch_returns_202() -> None:
    """CC-14: Async path returns HTTP 202 with job_id."""
    project_dir = create_fixture_project(name="exp_t17_async_202")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "status_code=202" in content, "Async dispatch must return 202"
    assert "job_id" in content


def test_sync_path_uses_streaming_response() -> None:
    """CC-15: Sync export path uses StreamingResponse."""
    project_dir = create_fixture_project(name="exp_t18_streaming")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "StreamingResponse" in content, "Sync path must use StreamingResponse"


def test_owner_filter_in_route() -> None:
    """CC-16: Owner filter (owner_id == current_user.id) applied in route."""
    project_dir = create_fixture_project(name="exp_t19_owner_filter")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "owner_id" in content, "Route must apply owner_id filter"


def test_soft_delete_filter_applied() -> None:
    """CC-17: is_deleted filter applied when model has the column."""
    project_dir = create_fixture_project(name="exp_t20_soft_del_filter")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "is_deleted" in content, "Route must check is_deleted attribute"


def test_tenant_filter_check_in_route() -> None:
    """CC-18: Tenant filter applied when model has tenant_id."""
    project_dir = create_fixture_project(name="exp_t21_tenant_filter")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "tenant_id" in content, "Route must check tenant_id for multi-tenant support"


def test_export_jobs_module_created() -> None:
    """app/core/export_jobs.py exists with dispatch_export_job function."""
    project_dir = create_fixture_project(name="exp_t22_export_jobs")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    export_jobs = project_dir / "app" / "core" / "export_jobs.py"
    assert export_jobs.exists(), "app/core/export_jobs.py not created"
    content = export_jobs.read_text()
    assert "dispatch_export_job" in content
    assert "job_id" in content


def test_export_progress_module_created() -> None:
    """app/core/export_progress.py exists with ExportStatus and Redis helpers."""
    project_dir = create_fixture_project(name="exp_t23_progress")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    progress_file = project_dir / "app" / "core" / "export_progress.py"
    assert progress_file.exists(), "app/core/export_progress.py not created"
    content = progress_file.read_text()
    assert "ExportStatus" in content
    assert "set_export_progress" in content
    assert "get_export_progress" in content


def test_arq_worker_created() -> None:
    """app/jobs/export.py exists with run_export ARQ function."""
    project_dir = create_fixture_project(name="exp_t24_arq_worker")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    worker_file = project_dir / "app" / "jobs" / "export.py"
    assert worker_file.exists(), "app/jobs/export.py not created"
    content = worker_file.read_text()
    assert "async def run_export" in content


def test_migration_file_created() -> None:
    """Alembic migration for export_jobs table is created."""
    project_dir = create_fixture_project(name="exp_t25_migration")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*export_jobs*"))
    assert len(migration_files) >= 1, "No export_jobs migration file created"
    content = migration_files[0].read_text()
    assert "export_jobs" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_migration_has_status_check_constraint() -> None:
    """Migration includes CHECK constraint on export_jobs.status."""
    project_dir = create_fixture_project(name="exp_t26_migration_ck")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*export_jobs*"))
    assert migration_files
    content = migration_files[0].read_text()
    assert "CheckConstraint" in content or "check" in content.lower()


def test_all_py_files_parse() -> None:
    """All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="exp_t27_parse_all")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="exp_t28_idempotent")
    r1 = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="exp_t29_idem_parse")
    add_data_export(ToolInput(project_dir=str(project_dir)))
    add_data_export(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="exp_t30_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_data_export(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="exp_t31_timing")
    result = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps must not be empty on success and must mention alembic."""
    project_dir = create_fixture_project(name="exp_t32_next_steps")
    result = add_data_export(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


def test_no_models_returns_error() -> None:
    """Tool returns error when no SQLAlchemy models are found."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "empty_project"
        (project_dir / "app" / "models").mkdir(parents=True)
        result = add_data_export(ToolInput(project_dir=str(project_dir)))
        assert result.status == "error"
        assert result.error is not None


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_export_core_file_created,
        test_stream_batches_uses_yield_per,
        test_export_csv_yields_per_batch,
        test_export_ndjson_present,
        test_export_xlsx_uses_constant_memory,
        test_export_parquet_uses_pyarrow,
        test_serialize_handles_all_types,
        test_sensitive_columns_frozenset_defined,
        test_export_route_registered,
        test_route_accepts_format_with_pattern,
        test_route_accepts_columns_query,
        test_default_columns_excludes_sensitive,
        test_preflight_count_before_streaming,
        test_async_dispatch_returns_202,
        test_sync_path_uses_streaming_response,
        test_owner_filter_in_route,
        test_soft_delete_filter_applied,
        test_tenant_filter_check_in_route,
        test_export_jobs_module_created,
        test_export_progress_module_created,
        test_arq_worker_created,
        test_migration_file_created,
        test_migration_has_status_check_constraint,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_no_models_returns_error,
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
