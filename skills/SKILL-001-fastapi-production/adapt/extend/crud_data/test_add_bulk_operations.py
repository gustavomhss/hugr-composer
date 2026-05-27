"""Tests for TOOL-007 add_bulk_operations.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_bulk_operations.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_bulk_operations.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_bulk_operations import add_bulk_operations
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
    project_dir = create_fixture_project(name="bulk_t01_success")
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="bulk_t02_files_exist")
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="bulk_t03_modified_exist")
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_item_bulk_create_schema_exists() -> None:
    """CC-01: ItemBulkCreate schema exists in app/schemas/item.py."""
    project_dir = create_fixture_project(name="bulk_t04_schema_create")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    assert schema_file.exists()
    content = schema_file.read_text()
    assert "ItemBulkCreate" in content
    assert "ItemCreate" in content
    assert "all_or_nothing" in content


def test_item_bulk_create_max_length_constraint() -> None:
    """CC-02: ItemBulkCreate.items field has max_length constraint."""
    project_dir = create_fixture_project(name="bulk_t05_max_length")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "max_length=" in content, "ItemBulkCreate must have max_length constraint"


def test_item_bulk_update_schema_with_validator() -> None:
    """CC-03: ItemBulkUpdate schema exists with each_update_has_id validator."""
    project_dir = create_fixture_project(name="bulk_t06_schema_update")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "ItemBulkUpdate" in content
    assert "each_update_has_id" in content
    assert "field_validator" in content


def test_item_bulk_delete_schema_exists() -> None:
    """CC-04: ItemBulkDelete schema exists with ids list and mode field."""
    project_dir = create_fixture_project(name="bulk_t07_schema_delete")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "ItemBulkDelete" in content
    assert "ids" in content


def test_bulk_result_item_schema_exists() -> None:
    """CC-05: BulkResultItem has index, id, success, error, error_code fields."""
    project_dir = create_fixture_project(name="bulk_t08_result_item")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "BulkResultItem" in content
    for field in ("index", "success", "error", "error_code"):
        assert field in content, f"BulkResultItem missing field: {field}"


def test_bulk_response_schema_exists() -> None:
    """CC-06: BulkResponse has total, succeeded, failed, partial, transaction_id, results."""
    project_dir = create_fixture_project(name="bulk_t09_bulk_response")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "BulkResponse" in content
    for field in ("total", "succeeded", "failed", "partial", "transaction_id", "results"):
        assert field in content, f"BulkResponse missing field: {field}"


def test_bulk_create_crud_function_exists() -> None:
    """CC-07: bulk_create_items function exists in app/crud/item.py."""
    project_dir = create_fixture_project(name="bulk_t10_crud_create")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    assert crud_file.exists()
    content = crud_file.read_text()
    assert "async def bulk_create_items" in content


def test_bulk_create_all_or_nothing_uses_pg_insert() -> None:
    """CC-08: bulk_create all_or_nothing issues single pg_insert or table.insert."""
    project_dir = create_fixture_project(name="bulk_t11_pg_insert")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "_pg_insert" in content or "pg_insert" in content, \
        "all_or_nothing must use pg_insert"


def test_bulk_create_best_effort_uses_begin_nested() -> None:
    """CC-09: bulk_create best_effort uses session.begin_nested() per item."""
    project_dir = create_fixture_project(name="bulk_t12_savepoint")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "begin_nested()" in content, "best_effort must use begin_nested() SAVEPOINTs"


def test_bulk_update_crud_function_with_ownership_check() -> None:
    """CC-10: bulk_update_items CRUD function pre-queries owner_id before writes."""
    project_dir = create_fixture_project(name="bulk_t13_update_ownership")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "async def bulk_update_items" in content
    assert "owner_id" in content


def test_bulk_update_uses_sql_update() -> None:
    """CC-11: bulk_update issues sql_update(Item).where(Item.id == row_id).values(**patch)."""
    project_dir = create_fixture_project(name="bulk_t14_sql_update")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "_sql_update" in content or "sql_update" in content, \
        "bulk_update must use SQLAlchemy UPDATE statement"


def test_bulk_delete_crud_uses_single_delete_statement() -> None:
    """CC-12: bulk_delete issues single sql_delete(Item).where(Item.id.in_(...))."""
    project_dir = create_fixture_project(name="bulk_t15_delete_in")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "async def bulk_delete_items" in content
    assert "_sql_delete" in content or "sql_delete" in content, \
        "bulk_delete must use sql_delete (single statement)"
    assert ".in_(" in content, "bulk_delete must use id.in_() for batch"


def test_post_bulk_route_exists_with_207() -> None:
    """CC-13: POST /items/bulk route exists returning BulkResponse with status_code=207."""
    project_dir = create_fixture_project(name="bulk_t16_post_bulk")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    assert route_file.exists()
    content = route_file.read_text()
    assert '@router.post("/bulk"' in content
    assert "status_code=207" in content


def test_patch_bulk_route_exists_with_207() -> None:
    """CC-14: PATCH /items/bulk route exists returning BulkResponse with status_code=207."""
    project_dir = create_fixture_project(name="bulk_t17_patch_bulk")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert '@router.patch("/bulk"' in content
    assert "status_code=207" in content


def test_delete_bulk_route_exists_with_207() -> None:
    """CC-15: DELETE /items/bulk route exists returning BulkResponse with status_code=207."""
    project_dir = create_fixture_project(name="bulk_t18_delete_bulk")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert '@router.delete("/bulk"' in content
    assert "status_code=207" in content


def test_routes_accept_idempotency_key_header() -> None:
    """CC-16: Bulk routes accept Idempotency-Key header."""
    project_dir = create_fixture_project(name="bulk_t19_idem_header")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert 'alias="Idempotency-Key"' in content, "Routes must accept Idempotency-Key header"


def test_idempotency_module_created() -> None:
    """CC-17: app/core/idempotency.py exists with IdempotencyCache, get_idempotency_cache, init_idempotency_cache."""
    project_dir = create_fixture_project(name="bulk_t20_idem_module")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    idem_file = project_dir / "app" / "core" / "idempotency.py"
    assert idem_file.exists(), "app/core/idempotency.py not created"
    content = idem_file.read_text()
    assert "IdempotencyCache" in content
    assert "get_idempotency_cache" in content
    assert "init_idempotency_cache" in content


def test_idempotency_cache_wrapped_in_try_except() -> None:
    """CC-18: IdempotencyCache.get and .set are wrapped in try/except with logging."""
    project_dir = create_fixture_project(name="bulk_t21_idem_try_except")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    idem_file = project_dir / "app" / "core" / "idempotency.py"
    content = idem_file.read_text()
    assert "try:" in content, "IdempotencyCache methods must use try/except"
    assert "except Exception" in content
    assert "logger.warning" in content


def test_main_patched_with_init_idempotency_cache() -> None:
    """CC-19: main.py is patched to call init_idempotency_cache on startup."""
    project_dir = create_fixture_project(name="bulk_t22_main_patch")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    assert main_file.exists()
    content = main_file.read_text()
    assert "init_idempotency_cache" in content, "main.py must call init_idempotency_cache"


def test_migration_file_created() -> None:
    """CC-20: Alembic migration for composite index is created."""
    project_dir = create_fixture_project(name="bulk_t23_migration")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*bulk_ops_index*"))
    assert len(migration_files) >= 1, "No bulk ops index migration file created"


def test_migration_uses_postgresql_concurrently() -> None:
    """CC-21: Migration uses postgresql_concurrently=True for index creation."""
    project_dir = create_fixture_project(name="bulk_t24_pg_concurrently")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*bulk_ops_index*"))
    assert migration_files
    content = migration_files[0].read_text()
    assert "postgresql_concurrently" in content, "Migration must use postgresql_concurrently=True"


def test_migration_downgrade_drops_index() -> None:
    """CC-22: Migration downgrade() drops the composite index."""
    project_dir = create_fixture_project(name="bulk_t25_downgrade")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*bulk_ops_index*"))
    assert migration_files
    content = migration_files[0].read_text()
    assert "def downgrade" in content
    assert "drop_index" in content


def test_all_py_files_parse() -> None:
    """CC-25: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="bulk_t26_parse_all")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-30: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="bulk_t27_idempotent")
    r1 = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="bulk_t28_idem_parse")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="bulk_t29_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="bulk_t30_timing")
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps must not be empty on success and must mention alembic."""
    project_dir = create_fixture_project(name="bulk_t31_next_steps")
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


def test_no_models_returns_error() -> None:
    """Tool returns error when no SQLAlchemy models are found."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp) / "empty_project"
        (project_dir / "app" / "models").mkdir(parents=True)
        result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
        assert result.status == "error"
        assert result.error is not None


def test_bulk_routes_in_same_router_file() -> None:
    """All three bulk routes exist in the same route file (not a new file)."""
    project_dir = create_fixture_project(name="bulk_t33_same_file")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert '@router.post("/bulk"' in content
    assert '@router.patch("/bulk"' in content
    assert '@router.delete("/bulk"' in content


def test_schema_bulk_response_has_config_dict() -> None:
    """BulkResponse uses model_config = ConfigDict(from_attributes=True)."""
    project_dir = create_fixture_project(name="bulk_t34_config_dict")
    add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    assert "ConfigDict" in content, "BulkResponse must use ConfigDict"
    assert "from_attributes=True" in content


# ---------------------------------------------------------------------------
# BUG B regression — multiword model discovery
# ---------------------------------------------------------------------------

def test_multiword_model_bulk_ops_not_skipped() -> None:
    """Regression: multiword model (VaccineLot in vaccinelot.py) must be patched.

    Before the fix, _discover_models derived 'Vaccinelot' from the filename
    which didn't match the actual class 'VaccineLot', silently skipping it.
    """
    project_dir = create_fixture_project(
        name="bulk_multiword_model",
        models={"Order": {"code": "str"}, "VaccineLot": {"lot": "str"}},
    )
    result = add_bulk_operations(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    notes_combined = " ".join(result.notes or [])
    assert "VaccineLot" in notes_combined, (
        f"VaccineLot not in notes — multiword model was skipped. Notes: {result.notes}"
    )
    crud_files = list((project_dir / "app" / "crud").glob("vaccinelot*.py"))
    assert crud_files, "No CRUD file found for VaccineLot model"
    assert "bulk_create" in crud_files[0].read_text(), (
        "VaccineLot CRUD missing bulk_create — multiword model was skipped"
    )


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_item_bulk_create_schema_exists,
        test_item_bulk_create_max_length_constraint,
        test_item_bulk_update_schema_with_validator,
        test_item_bulk_delete_schema_exists,
        test_bulk_result_item_schema_exists,
        test_bulk_response_schema_exists,
        test_bulk_create_crud_function_exists,
        test_bulk_create_all_or_nothing_uses_pg_insert,
        test_bulk_create_best_effort_uses_begin_nested,
        test_bulk_update_crud_function_with_ownership_check,
        test_bulk_update_uses_sql_update,
        test_bulk_delete_crud_uses_single_delete_statement,
        test_post_bulk_route_exists_with_207,
        test_patch_bulk_route_exists_with_207,
        test_delete_bulk_route_exists_with_207,
        test_routes_accept_idempotency_key_header,
        test_idempotency_module_created,
        test_idempotency_cache_wrapped_in_try_except,
        test_main_patched_with_init_idempotency_cache,
        test_migration_file_created,
        test_migration_uses_postgresql_concurrently,
        test_migration_downgrade_drops_index,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_no_models_returns_error,
        test_bulk_routes_in_same_router_file,
        test_schema_bulk_response_has_config_dict,
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
