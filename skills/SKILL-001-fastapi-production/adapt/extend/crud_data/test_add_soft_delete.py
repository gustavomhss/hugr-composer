"""Structural tests for the refactored TOOL-001 ``add_soft_delete``.

P1-#14 RESOLUTION: the tool now patches ``CRUDBase`` directly (single source
of truth) instead of emitting per-model module shadows + an orphan UoW glue
file at ``app/soft_delete.py``. Tests reflect that new shape:

* No ``app/soft_delete.py`` is written.
* No ``async def get/get_multi/delete`` shadows appear in per-model CRUD files.
* ``app/crud/base.py`` carries the ``SOFT_DELETE_PATCH_APPLIED`` fingerprint
  and reassigns ``CRUDBase.get/get_multi/delete`` to soft-delete-aware
  callables.
"""

from __future__ import annotations

import ast
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


def test_no_orphan_uow_glue_file() -> None:
    """P1-#14: app/soft_delete.py orphan UoW glue must NOT be emitted."""
    p = create_fixture_project(name="sd_t04_no_orphan")
    r = add_soft_delete(ToolInput(project_dir=str(p)))
    assert r.status == "success"
    assert not (p / "app" / "soft_delete.py").exists(), (
        "app/soft_delete.py must not be emitted — nothing imports it (orphan UoW)."
    )
    # Same belt-and-suspenders check via files_created.
    assert not any(s.endswith("/app/soft_delete.py") for s in r.files_created), (
        "files_created must not list app/soft_delete.py."
    )


def test_no_uow_primitive_copied() -> None:
    """P1-#14: UnitOfWork primitive must NOT be copied — it was only used by the orphan glue."""
    p = create_fixture_project(name="sd_t05_no_uow")
    add_soft_delete(ToolInput(project_dir=str(p)))
    uow = p / "core" / "venous" / "data" / "UnitOfWork" / "UnitOfWork.py"
    adapter = p / "core" / "venous" / "_adapters" / "fastapi" / "UnitOfWorkAdapter.py"
    assert not uow.exists(), "UnitOfWork primitive should not be copied — it had no real consumer."
    assert not adapter.exists(), "UnitOfWorkAdapter should not be copied — it had no real consumer."


def test_mcp_tool_no_longer_lists_uow_imports() -> None:
    """MCP_TOOL no longer claims to import the UoW primitive/adapter."""
    assert (
        "imports_primitives" not in MCP_TOOL
        or "core.venous.data.UnitOfWork" not in MCP_TOOL.get("imports_primitives", [])
    )
    assert (
        "imports_adapters" not in MCP_TOOL
        or "core.venous._adapters.fastapi.UnitOfWorkAdapter"
        not in MCP_TOOL.get("imports_adapters", [])
    )


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
    to any model. The fix actually injects the column.
    """
    p = create_fixture_project(name="sd_bugc_model_col")
    add_soft_delete(ToolInput(project_dir=str(p)))
    model_file = p / "app" / "models" / "item.py"
    assert model_file.exists(), "Model file item.py not found"
    content = model_file.read_text()
    assert "is_deleted" in content, (
        "is_deleted column NOT found in model — soft-delete is still inert (BUG C regression)"
    )
    assert "deleted_at" in content, "deleted_at column NOT found in model"


def test_migration_added_for_is_deleted() -> None:
    """BUG C regression: a migration adding is_deleted must be generated."""
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


def test_crudbase_patched_with_fingerprint() -> None:
    """P1-#14: app/crud/base.py must carry the SOFT_DELETE_PATCH_APPLIED fingerprint."""
    p = create_fixture_project(name="sd_p1_14_fingerprint")
    add_soft_delete(ToolInput(project_dir=str(p)))
    crud_base = p / "app" / "crud" / "base.py"
    assert crud_base.exists(), "crud/base.py missing in scaffolded project"
    content = crud_base.read_text()
    assert "SOFT_DELETE_PATCH_APPLIED" in content, (
        "CRUDBase patch fingerprint missing — soft-delete patch was not applied to crud/base.py."
    )
    # The three method reassignments must be present.
    assert "CRUDBase.get = _sd_get" in content
    assert "CRUDBase.get_multi = _sd_get_multi" in content
    assert "CRUDBase.delete = _sd_delete" in content


def test_crudbase_methods_soft_delete_aware() -> None:
    """P1-#14: the patched CRUDBase methods filter is_deleted and flip the flag on delete."""
    p = create_fixture_project(name="sd_p1_14_methods")
    add_soft_delete(ToolInput(project_dir=str(p)))
    content = (p / "app" / "crud" / "base.py").read_text()

    # get and get_multi must guard with hasattr(is_deleted) and filter when present.
    assert content.count("is_deleted == False") >= 2, (
        "get() and get_multi() must each filter is_deleted == False."
    )
    assert content.count('hasattr(self.model, "is_deleted")') >= 2, (
        "Both reads must check hasattr(self.model, 'is_deleted') so non-soft-delete models keep working."
    )
    # delete must flip the flag (not call session.delete on soft-delete models).
    assert "obj.is_deleted = True" in content, (
        "CRUDBase.delete must set obj.is_deleted = True for soft-delete-aware behaviour."
    )


def test_per_model_crud_unshadowed() -> None:
    """P1-#14: per-model CRUD files must NOT contain module-level get/get_multi/delete shadows.

    The previous tool wrote ``async def get(...)`` etc at module scope, neutralising the
    ``get = crud.get`` re-export aliases. The new tool patches CRUDBase directly, so the
    per-model CRUD files stay vanilla.
    """
    p = create_fixture_project(name="sd_p1_14_unshadowed")
    add_soft_delete(ToolInput(project_dir=str(p)))
    crud_item = p / "app" / "crud" / "item.py"
    content = crud_item.read_text()
    # No async-def shadows.
    assert "async def get(" not in content, "per-model CRUD must not shadow get()"
    assert "async def get_multi(" not in content, "per-model CRUD must not shadow get_multi()"
    assert "async def delete(" not in content, "per-model CRUD must not shadow delete()"
    # The re-export aliases must NOT be neutralised — they must still bind crud.<fn>.
    assert "get = crud.get" in content, "per-model re-export `get = crud.get` must remain intact"
    assert "get_multi = crud.get_multi" in content
    assert "delete = crud.delete" in content
    # And no commented-out / neutralised variant should leak through.
    assert "# get = crud.get" not in content
    assert "# delete = crud.delete" not in content


def test_model_file_still_parses_after_injection() -> None:
    """BUG C regression: model file must remain valid Python after column injection."""
    p = create_fixture_project(name="sd_bugc_parse_model")
    add_soft_delete(ToolInput(project_dir=str(p)))
    for f in sorted((p / "app" / "models").glob("*.py")):
        try:
            ast.parse(f.read_text())
        except SyntaxError as exc:
            raise AssertionError(
                f"Model file {f} has SyntaxError after soft-delete injection: {exc}"
            ) from exc


def test_soft_delete_works_on_multiword_model() -> None:
    """Multiword model must get is_deleted injected without breaking discovery."""
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
    """Generated soft_delete migration must parse as valid Python."""
    p = create_fixture_project(name="sd_bugc_mig_parse")
    add_soft_delete(ToolInput(project_dir=str(p)))
    for mig in (p / "alembic" / "versions").glob("*soft_delete*"):
        try:
            ast.parse(mig.read_text())
        except SyntaxError as exc:
            raise AssertionError(f"Migration {mig} has SyntaxError: {exc}") from exc


def test_crudbase_imports_added_idempotently() -> None:
    """Running twice must not duplicate the CRUDBase patch block."""
    p = create_fixture_project(name="sd_p1_14_idempotent_patch")
    add_soft_delete(ToolInput(project_dir=str(p)))
    add_soft_delete(ToolInput(project_dir=str(p)))
    content = (p / "app" / "crud" / "base.py").read_text()
    assert content.count("SOFT_DELETE_PATCH_APPLIED") == 1, (
        "CRUDBase patch must be applied at most once."
    )
    assert content.count("CRUDBase.get = _sd_get") == 1, (
        "CRUDBase.get reassignment must not be duplicated."
    )


if __name__ == "__main__":
    tests = [
        test_success_status,
        test_idempotent,
        test_dry_run_writes_nothing,
        test_no_orphan_uow_glue_file,
        test_no_uow_primitive_copied,
        test_mcp_tool_no_longer_lists_uow_imports,
        test_all_py_parse_after_two_runs,
        test_execution_time_recorded,
        # BUG C regressions
        test_is_deleted_column_injected_into_model,
        test_migration_added_for_is_deleted,
        # P1-#14 — CRUDBase-as-source-of-truth
        test_crudbase_patched_with_fingerprint,
        test_crudbase_methods_soft_delete_aware,
        test_per_model_crud_unshadowed,
        test_crudbase_imports_added_idempotently,
        test_model_file_still_parses_after_injection,
        test_soft_delete_works_on_multiword_model,
        test_migration_is_valid_python,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
        else:
            print(f"  PASS  {t.__name__}")
            passed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if not failed else 1)
