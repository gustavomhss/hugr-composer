"""Tests for TOOL-001 add_soft_delete.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/crud_data/test_add_soft_delete.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/crud_data/test_add_soft_delete.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import add_soft_delete
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
    project_dir = create_fixture_project(name="t01_success")
    result = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="t02_files_exist")
    result = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="t03_modified_exist")
    result = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_mixin_file_created() -> None:
    """CC-01: app/models/mixins.py exists and contains SoftDeleteMixin."""
    project_dir = create_fixture_project(name="t04_mixin")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    mixin_file = project_dir / "app" / "models" / "mixins.py"
    assert mixin_file.exists(), "mixins.py not created"
    content = mixin_file.read_text()
    assert "SoftDeleteMixin" in content
    assert "is_deleted" in content
    assert "deleted_at" in content
    assert "deleted_by" in content


def test_model_inherits_mixin() -> None:
    """CC-02: Target model class inherits SoftDeleteMixin."""
    project_dir = create_fixture_project(name="t05_model_inherits")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "item.py"
    assert model_file.exists()
    content = model_file.read_text()
    assert "SoftDeleteMixin" in content, "Model does not inherit SoftDeleteMixin"
    assert "class Item(SoftDeleteMixin, Base)" in content


def test_filter_file_created() -> None:
    """CC-07: app/core/soft_delete_filter.py exists with the listener."""
    project_dir = create_fixture_project(name="t06_filter")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    filter_file = project_dir / "app" / "core" / "soft_delete_filter.py"
    assert filter_file.exists(), "soft_delete_filter.py not created"
    content = filter_file.read_text()
    assert "do_orm_execute" in content
    assert "with_loader_criteria" in content
    assert "include_deleted" in content


def test_main_imports_filter() -> None:
    """CC-08: main.py imports soft_delete_filter (side-effect import)."""
    project_dir = create_fixture_project(name="t07_main_import")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    assert main_file.exists()
    assert "soft_delete_filter" in main_file.read_text()


def test_crud_helpers_added() -> None:
    """CC-10..14: CRUD file has soft_delete, restore, hard_delete, list_deleted."""
    project_dir = create_fixture_project(name="t08_crud")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    assert crud_file.exists()
    content = crud_file.read_text()
    for fn in ("soft_delete", "restore", "hard_delete", "list_deleted"):
        assert f"async def {fn}" in content, f"Missing function: {fn}"


def test_crud_soft_delete_uses_utc() -> None:
    """CC-11: soft_delete uses datetime.now(timezone.utc) not naive datetime."""
    project_dir = create_fixture_project(name="t09_utc")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    assert "timezone.utc" in content or "_tz.utc" in content, "soft_delete must use UTC"


def test_crud_soft_delete_no_session_delete() -> None:
    """CC-12: soft_delete does NOT call session.delete()."""
    project_dir = create_fixture_project(name="t10_no_hard_del")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    content = crud_file.read_text()
    # Find the soft_delete function body only
    sd_start = content.find("async def soft_delete")
    sd_end = content.find("\nasync def restore", sd_start)
    soft_delete_body = content[sd_start:sd_end]
    assert "session.delete" not in soft_delete_body, "soft_delete must NOT call session.delete()"


def test_routes_soft_delete_endpoints() -> None:
    """CC-16..19: Route file has delete, restore, hard_delete, list_deleted endpoints."""
    project_dir = create_fixture_project(name="t11_routes")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    assert route_file.exists()
    content = route_file.read_text()
    assert "async def delete_item" in content
    assert "async def restore_item" in content
    assert "async def hard_delete_item" in content
    assert "async def list_deleted_items" in content


def test_routes_use_superuser_dep() -> None:
    """CC-17/18/19: restore, hard_delete, list_deleted routes need CurrentSuperuser."""
    project_dir = create_fixture_project(name="t12_superuser")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    route_file = project_dir / "app" / "api" / "routes" / "item.py"
    content = route_file.read_text()
    assert "CurrentSuperuser" in content, "Routes must use CurrentSuperuser"


def test_schema_deleted_public_added() -> None:
    """CC-20: Schema file gets ItemDeletedPublic and ItemsDeletedPublic."""
    project_dir = create_fixture_project(name="t13_schema")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    assert schema_file.exists()
    content = schema_file.read_text()
    assert "ItemDeletedPublic" in content
    assert "ItemsDeletedPublic" in content


def test_item_public_excludes_soft_delete_fields() -> None:
    """CC-21: ItemPublic does NOT contain is_deleted, deleted_at, deleted_by."""
    project_dir = create_fixture_project(name="t14_public_schema")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "item.py"
    content = schema_file.read_text()
    # Find ItemPublic class body only (stop at next class)
    pub_start = content.find("class ItemPublic")
    pub_end = content.find("\nclass ", pub_start + 1)
    item_public_body = content[pub_start:pub_end] if pub_end != -1 else content[pub_start:]
    for field in ("is_deleted", "deleted_at", "deleted_by"):
        assert field not in item_public_body, f"ItemPublic must NOT expose {field}"


def test_migration_file_created() -> None:
    """CC-22..26: Alembic migration file is created with correct content."""
    project_dir = create_fixture_project(name="t15_migration")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*softdel_items*"))
    assert len(migration_files) >= 1, "No soft-delete migration file created"
    content = migration_files[0].read_text()
    assert "is_deleted" in content
    assert "deleted_at" in content
    assert "deleted_by" in content
    assert "server_default=sa.false()" in content
    assert "ix_items_active" in content
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_all_py_files_parse() -> None:
    """CC-27: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="t16_parse_all")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)  # raises AssertionError on SyntaxError


def test_idempotent_returns_no_op() -> None:
    """CC-32 / QS-06: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="t17_idempotent")
    r1 = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="t18_idempotent_parse")
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    add_soft_delete(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="t19_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_soft_delete(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    # No file on disk changed
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="t20_timing")
    result = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


def test_next_steps_present() -> None:
    """next_steps should guide the developer after a successful run."""
    project_dir = create_fixture_project(name="t21_next_steps")
    result = add_soft_delete(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0, "next_steps must not be empty on success"
    assert any("alembic" in s for s in result.next_steps), "Should mention alembic upgrade"


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_mixin_file_created,
        test_model_inherits_mixin,
        test_filter_file_created,
        test_main_imports_filter,
        test_crud_helpers_added,
        test_crud_soft_delete_uses_utc,
        test_crud_soft_delete_no_session_delete,
        test_routes_soft_delete_endpoints,
        test_routes_use_superuser_dep,
        test_schema_deleted_public_added,
        test_item_public_excludes_soft_delete_fields,
        test_migration_file_created,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
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
