"""Structural tests for the refactored TOOL-001 ``add_soft_delete``.

Mirrors the three-step `add_graceful_shutdown` delivery contract.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.crud_data.add_soft_delete import MCP_TOOL, add_soft_delete
from tests.common.fixture_factory import create_fixture_project


def _all_py_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py_files(root):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:  # pragma: no cover
            raise AssertionError(f"SyntaxError in {f}: {exc}") from exc


def test_success_status() -> None:
    p = create_fixture_project(name="sd_t01")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.status == "success", r.error


def test_idempotent() -> None:
    p = create_fixture_project(name="sd_t02")
    add_soft_delete(ToolInput(project_dir=str(p)))
    r2 = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r2.status == "no_op"


def test_dry_run_writes_nothing() -> None:
    p = create_fixture_project(name="sd_t03")
    before = {f: f.read_text() for f in _all_py_files(p)}
    r = add_soft_delete(ToolInput(project_dir=str(p), dry_run=True))
    assert r.status == "success"
    after = {f: f.read_text() for f in _all_py_files(p)}
    assert before == after


def test_primitive_copied() -> None:
    p = create_fixture_project(name="sd_t04")
    add_soft_delete(ToolInput(project_dir=str(p)))
    uow = p / "core" / "venous" / "data" / "UnitOfWork" / "UnitOfWork.py"
    assert uow.exists()
    assert "class InMemoryUnitOfWork" in uow.read_text()


def test_adapter_copied() -> None:
    p = create_fixture_project(name="sd_t05")
    add_soft_delete(ToolInput(project_dir=str(p)))
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "UnitOfWorkAdapter.py"
    assert adapter.exists()
    assert "def make_dependency(" in adapter.read_text()


def test_manifest_records_provenance() -> None:
    p = create_fixture_project(name="sd_t06")
    add_soft_delete(ToolInput(project_dir=str(p)))
    m = json.loads((p / ".venous_manifest.json").read_text())
    assert "core.venous.data.UnitOfWork" in {x["qualified_name"] for x in m["primitives"]}
    assert "core.venous._adapters.fastapi.UnitOfWorkAdapter" in {x["qualified_name"] for x in m["adapters"]}


def test_glue_imports_adapter() -> None:
    p = create_fixture_project(name="sd_t07")
    add_soft_delete(ToolInput(project_dir=str(p)))
    body = (p / "app" / "soft_delete.py").read_text()
    assert "from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency" in body


def test_glue_under_20_loc_body() -> None:
    p = create_fixture_project(name="sd_t08")
    add_soft_delete(ToolInput(project_dir=str(p)))
    glue = p / "app" / "soft_delete.py"
    tree = ast.parse(glue.read_text())
    body_lines = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_lines += (node.end_lineno or node.body[0].lineno) - node.body[0].lineno + 1
    assert body_lines <= 20


def test_mcp_tool_lists_imports() -> None:
    assert "core.venous.data.UnitOfWork" in MCP_TOOL["imports_primitives"]
    assert "core.venous._adapters.fastapi.UnitOfWorkAdapter" in MCP_TOOL["imports_adapters"]


def test_all_py_parse_after_two_runs() -> None:
    p = create_fixture_project(name="sd_t10")
    add_soft_delete(ToolInput(project_dir=str(p)))
    add_soft_delete(ToolInput(project_dir=str(p)))
    _assert_parse(p)


def test_execution_time_recorded() -> None:
    p = create_fixture_project(name="sd_t11")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.execution_time_ms > 0


# ---------------------------------------------------------------------------
# Regression tests for BUG C (inert/no-op while reporting success)
# ---------------------------------------------------------------------------

def test_is_deleted_column_injected_into_model() -> None:
    """BUG C regression: is_deleted column must be present in the model file after tool runs.

    The old implementation returned status='success' but never added is_deleted
    to any model.  The fix actually injects the column.
    """
    p = create_fixture_project(name="sd_bugc_model_col")
    add_soft_delete(ToolInput(project_dir=str(p)))
    model_file = p / "app" / "models" / "item.py"
    assert model_file.exists(), "Model file item.py not found"
    content = model_file.read_text()
    assert "is_deleted" in content, (
        "is_deleted column NOT found in model — soft-delete is still inert (BUG C regression)"
    )
    assert "deleted_at" in content, (
        "deleted_at column NOT found in model"
    )


def test_migration_added_for_is_deleted() -> None:
    """BUG C regression: a migration adding is_deleted must be generated.

    The old implementation never emitted a migration for is_deleted.
    """
    p = create_fixture_project(name="sd_bugc_migration")
    add_soft_delete(ToolInput(project_dir=str(p)))
    versions_dir = p / "alembic" / "versions"
    soft_delete_migrations = list(versions_dir.glob("*soft_delete*"))
    assert soft_delete_migrations, (
        "No soft_delete migration found — is_deleted column has no schema migration (BUG C regression)"
    )
    content = soft_delete_migrations[0].read_text()
    assert "is_deleted" in content, "Migration does not reference is_deleted"
    assert "deleted_at" in content, "Migration does not reference deleted_at"


def test_crud_delete_soft_deletes_not_hard_deletes() -> None:
    """BUG C regression: CRUD delete() must soft-delete (set is_deleted) not hard-delete."""
    p = create_fixture_project(name="sd_bugc_crud_soft")
    add_soft_delete(ToolInput(project_dir=str(p)))
    crud_file = p / "app" / "crud" / "item.py"
    assert crud_file.exists(), "CRUD file not found"
    content = crud_file.read_text()
    assert "is_deleted" in content, (
        "CRUD still has no is_deleted reference — delete() is still hard-deleting (BUG C regression)"
    )
    # The soft-delete override must set the flag
    assert "obj.is_deleted = True" in content, (
        "CRUD delete() does not set obj.is_deleted = True — hard-delete still active"
    )


def test_crud_reads_filter_deleted() -> None:
    """e2e 02_crud_lifecycle regression: BOTH read paths must hide soft-deleted rows.

    The first soft-delete rewrite overrode only delete() and added a dead
    get_multi_active() no route called, so GET-by-id of a soft-deleted row still
    returned 200 and list responses leaked soft-deleted rows.  The read paths the
    routes actually import are get() and get_multi(); both must be shadowed under
    those names (with the crud.<fn> aliases neutralized) and filter is_deleted.
    """
    p = create_fixture_project(name="sd_reads_filter")
    add_soft_delete(ToolInput(project_dir=str(p)))
    crud_file = p / "app" / "crud" / "item.py"
    content = crud_file.read_text()

    # Both read entry points the routes import must be overridden by name.
    assert "async def get(" in content, "CRUD must override get() so GET-by-id of a soft-deleted row 404s"
    assert "async def get_multi(" in content, "CRUD must override get_multi() to exclude soft-deleted rows"
    assert content.count("is_deleted == False") >= 3, (
        "get(), get_multi() and delete() must each filter is_deleted == False"
    )
    # The CRUDBase re-export aliases must be neutralized so the overrides win.
    assert "# get = crud.get" in content, "get = crud.get alias must be neutralized"
    assert "# get_multi = crud.get_multi" in content, "get_multi alias must be neutralized"
    assert "# delete = crud.delete" in content, "delete = crud.delete alias must be neutralized"


def test_model_file_still_parses_after_injection() -> None:
    """BUG C regression: model file must remain valid Python after column injection."""
    p = create_fixture_project(name="sd_bugc_parse_model")
    add_soft_delete(ToolInput(project_dir=str(p)))
    for f in sorted((p / "app" / "models").glob("*.py")):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:
            raise AssertionError(f"Model file {f} has SyntaxError after soft-delete injection: {exc}") from exc


def test_soft_delete_works_on_multiword_model() -> None:
    """BUG C regression (+ BUG B class-name cross-check): multiword model must get is_deleted injected."""
    p = create_fixture_project(
        name="sd_bugc_multiword",
        models={"VaccineLot": {"name": "str", "description": "str"}},
    )
    result = add_soft_delete(ToolInput(project_dir=str(p)))
    assert result.status == "success", f"Expected success for VaccineLot, got: {result.status}"
    model_file = p / "app" / "models" / "vaccinelot.py"
    assert model_file.exists(), "vaccinelot.py model file not found"
    content = model_file.read_text()
    assert "is_deleted" in content, "is_deleted not injected into VaccineLot model"


def test_migration_is_valid_python() -> None:
    """BUG C regression: generated soft_delete migration must parse as valid Python."""
    p = create_fixture_project(name="sd_bugc_mig_parse")
    add_soft_delete(ToolInput(project_dir=str(p)))
    for mig in (p / "alembic" / "versions").glob("*soft_delete*"):
        try:
            ast.parse(mig.read_text())
        except SyntaxError as exc:
            raise AssertionError(f"Migration {mig} has SyntaxError: {exc}") from exc


if __name__ == "__main__":
    tests = [
        test_success_status, test_idempotent, test_dry_run_writes_nothing,
        test_primitive_copied, test_adapter_copied, test_manifest_records_provenance,
        test_glue_imports_adapter, test_glue_under_20_loc_body, test_mcp_tool_lists_imports,
        test_all_py_parse_after_two_runs, test_execution_time_recorded,
        # BUG C regressions
        test_is_deleted_column_injected_into_model,
        test_migration_added_for_is_deleted,
        test_crud_delete_soft_deletes_not_hard_deletes,
        test_crud_reads_filter_deleted,
        test_model_file_still_parses_after_injection,
        test_soft_delete_works_on_multiword_model,
        test_migration_is_valid_python,
    ]
    p = f = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}"); p += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}"); f += 1
    print(f"\n{p}/{p+f} passed")
    sys.exit(0 if not f else 1)
