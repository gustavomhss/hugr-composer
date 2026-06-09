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
    """SPEC-v2: the model gains soft-delete columns by inheriting SoftDeleteMixin.

    Re-anchored from the OLD design (a literal ``is_deleted``/``deleted_at``
    column block injected into every model file). SPEC-v2 (#19) instead emits
    ``app/models/mixins.py::SoftDeleteMixin`` carrying the three deletion
    columns and rewrites each domain model's bases to inherit it, so the global
    ``do_orm_execute`` listener can key off that single mixin class. We assert
    the real shipped behaviour: the model imports + inherits the mixin, and the
    mixin actually declares all three deletion columns. This still fails if
    soft-delete is inert (no mixin emitted, model bases not rewritten).
    """
    p = create_fixture_project(name="sd_v2_model_col")
    add_soft_delete(ToolInput(project_dir=str(p)))

    model_file = p / "app" / "models" / "item.py"
    assert model_file.exists(), "Model file item.py not found"
    model_src = model_file.read_text()
    assert "from app.models.mixins import SoftDeleteMixin" in model_src, (
        "Model must import SoftDeleteMixin — soft-delete is inert otherwise."
    )
    # The Item class must actually inherit the mixin (not just import it).
    tree = ast.parse(model_src)
    item_cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Item"),
        None,
    )
    assert item_cls is not None, "Item class not found in model file"
    base_names = {b.id for b in item_cls.bases if isinstance(b, ast.Name)}
    assert "SoftDeleteMixin" in base_names, (
        "Item must inherit SoftDeleteMixin so it gains the deletion columns."
    )

    # The deletion columns live on the emitted mixin (single source of truth).
    mixin_file = p / "app" / "models" / "mixins.py"
    assert mixin_file.exists(), "app/models/mixins.py not emitted — columns have no home."
    mixin_src = mixin_file.read_text()
    assert "class SoftDeleteMixin" in mixin_src, "SoftDeleteMixin class not emitted."
    for col in ("is_deleted", "deleted_at", "deleted_by"):
        assert col in mixin_src, f"{col} column NOT defined on SoftDeleteMixin."


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
    """SPEC-v2: app/crud/base.py carries the fingerprint and re-points DELETE to soft-delete.

    Re-anchored from the OLD design (CRUDBase.get / get_multi / delete all
    reassigned to ``_sd_*`` callables that filtered ``is_deleted`` per query).
    SPEC-v2 (#19) moves read exclusion to the GLOBAL ``do_orm_execute`` filter,
    so CRUDBase.get / get_multi need NO per-query clause and are no longer
    patched; only ``CRUDBase.delete`` is overridden so the default DELETE route
    soft-deletes instead of issuing SQL DELETE (INV-SD-03). We assert the
    fingerprint + the real ``CRUDBase.delete`` reassignment, and that the read
    methods are deliberately NOT reassigned (would shadow the global filter).
    """
    p = create_fixture_project(name="sd_v2_fingerprint")
    add_soft_delete(ToolInput(project_dir=str(p)))
    crud_base = p / "app" / "crud" / "base.py"
    assert crud_base.exists(), "crud/base.py missing in scaffolded project"
    content = crud_base.read_text()
    assert "SOFT_DELETE_PATCH_APPLIED" in content, (
        "CRUDBase patch fingerprint missing — soft-delete patch was not applied to crud/base.py."
    )
    # delete() is re-pointed at the soft-delete-aware callable.
    assert "CRUDBase.delete = _sd_delete" in content, (
        "CRUDBase.delete must be reassigned to the soft-delete-aware override."
    )
    # Reads are filtered GLOBALLY (do_orm_execute), so they must NOT be reassigned
    # here — doing so would duplicate/shadow the global filter.
    assert "CRUDBase.get = " not in content, (
        "CRUDBase.get must NOT be reassigned — reads are filtered by the global "
        "do_orm_execute listener under SPEC-v2."
    )
    assert "CRUDBase.get_multi = " not in content, (
        "CRUDBase.get_multi must NOT be reassigned — reads are filtered globally."
    )


def test_crudbase_methods_soft_delete_aware() -> None:
    """SPEC-v2: reads are filtered by the global do_orm_execute listener; delete flips the flag.

    Re-anchored from the OLD design (per-query ``is_deleted == False`` clauses
    inside patched ``CRUDBase.get`` / ``get_multi`` guarded by
    ``hasattr(self.model, "is_deleted")``). SPEC-v2 (#19) implements read
    exclusion ONCE, globally, via the ``do_orm_execute`` SQLAlchemy listener
    using ``with_loader_criteria`` against ``SoftDeleteMixin`` (INV-SD-01); the
    listener is wired into ``app/main.py``. ``CRUDBase.delete`` still flips
    ``is_deleted=True`` instead of issuing SQL DELETE, behind a ``hasattr``
    guard so non-soft-delete models keep hard-delete (INV-SD-03). This still
    fails if either half of the mechanism is broken.
    """
    p = create_fixture_project(name="sd_v2_methods")
    add_soft_delete(ToolInput(project_dir=str(p)))
    app_dir = p / "app"

    # --- Global read exclusion (replaces the per-query get/get_multi clauses). ---
    filter_file = app_dir / "core" / "soft_delete_filter.py"
    assert filter_file.exists(), "app/core/soft_delete_filter.py not emitted."
    filter_src = filter_file.read_text()
    assert "do_orm_execute" in filter_src, (
        "Global filter must register a do_orm_execute listener (INV-SD-01)."
    )
    assert "with_loader_criteria" in filter_src, (
        "Global filter must use with_loader_criteria to inject the predicate."
    )
    assert "SoftDeleteMixin" in filter_src, (
        "Global filter must key off SoftDeleteMixin so every mixed-in model is filtered."
    )
    assert "is_deleted == False" in filter_src, (
        "Global filter must inject the is_deleted == False predicate."
    )
    assert "include_deleted" in filter_src, (
        "Global filter must honour the include_deleted execution option opt-out."
    )
    # The listener must actually be activated at startup.
    main_src = (app_dir / "main.py").read_text()
    assert "soft_delete_filter" in main_src, (
        "soft_delete_filter must be imported in main.py to register the listener."
    )

    # --- delete() flips the flag instead of hard-deleting soft-delete models. ---
    content = (app_dir / "crud" / "base.py").read_text()
    assert "obj.is_deleted = True" in content, (
        "CRUDBase.delete must set obj.is_deleted = True for soft-delete-aware behaviour."
    )
    assert 'hasattr(obj, "is_deleted")' in content, (
        "CRUDBase.delete must guard on hasattr(obj, 'is_deleted') so non-soft-delete "
        "models keep hard-delete."
    )
    assert "await session.delete(obj)" in content, (
        "CRUDBase.delete must still hard-delete models without is_deleted."
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
    """SPEC-v2: soft-delete works end-to-end for a multi-word model name.

    Re-anchored from the OLD design (assert a literal ``is_deleted`` injected
    into the model file). SPEC-v2 (#19) gives the multi-word model soft-delete
    via mixin inheritance + per-model crud helpers + an Alembic migration for
    the correctly-pluralized table. We prove the FULL machinery is wired for
    ``VaccineLot`` (snake stem ``vaccinelot``, table ``vaccinelots``), so this
    still fails if multi-word discovery or any soft-delete artefact breaks.
    """
    p = create_fixture_project(
        name="sd_v2_multiword",
        models={"VaccineLot": {"name": "str", "description": "str"}},
    )
    result = add_soft_delete(ToolInput(project_dir=str(p)))
    assert result.status == "success", f"Expected success for VaccineLot, got: {result.status}"

    # 1. Model inherits the mixin (the new way columns are added).
    model_file = p / "app" / "models" / "vaccinelot.py"
    assert model_file.exists(), "vaccinelot.py model file not found"
    model_src = model_file.read_text()
    assert "from app.models.mixins import SoftDeleteMixin" in model_src, (
        "Multi-word model must import SoftDeleteMixin."
    )
    tree = ast.parse(model_src)
    cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "VaccineLot"),
        None,
    )
    assert cls is not None, "VaccineLot class not found"
    base_names = {b.id for b in cls.bases if isinstance(b, ast.Name)}
    assert "SoftDeleteMixin" in base_names, (
        "VaccineLot must inherit SoftDeleteMixin — soft-delete inert for multi-word model otherwise."
    )

    # 2. Per-model CRUD helpers were appended for the multi-word model.
    crud_src = (p / "app" / "crud" / "vaccinelot.py").read_text()
    assert "async def soft_delete(" in crud_src, "soft_delete helper missing for VaccineLot."
    assert "async def restore(" in crud_src, "restore helper missing for VaccineLot."
    assert "obj.is_deleted = True" in crud_src, "VaccineLot soft_delete must flip is_deleted."

    # 3. Admin schema generated with the multi-word PascalCase name.
    schema_src = (p / "app" / "schemas" / "vaccinelot.py").read_text()
    assert "class VaccineLotDeletedPublic" in schema_src, (
        "Admin VaccineLotDeletedPublic schema missing for multi-word model."
    )

    # 4. Migration generated for the correctly-pluralized multi-word table.
    versions = p / "alembic" / "versions"
    migs = list(versions.glob("*soft_delete_vaccinelots*"))
    assert migs, "No soft_delete migration for the vaccinelots table (multi-word pluralization)."
    mig_src = migs[0].read_text()
    assert '"vaccinelots"' in mig_src, "Migration must target the vaccinelots table."
    assert "is_deleted" in mig_src, "Migration must add the is_deleted column."


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
    """SPEC-v2: running twice must not duplicate the CRUDBase soft-delete patch.

    Re-anchored: the OLD design counted ``CRUDBase.get = _sd_get`` (a read
    reassignment removed in #19). SPEC-v2 only re-points ``CRUDBase.delete``;
    idempotency is driven by the ``SOFT_DELETE_PATCH_APPLIED`` fingerprint. We
    assert both the fingerprint and the ``CRUDBase.delete`` reassignment appear
    exactly once after two runs (the second run is a no_op).
    """
    p = create_fixture_project(name="sd_v2_idempotent_patch")
    add_soft_delete(ToolInput(project_dir=str(p)))
    add_soft_delete(ToolInput(project_dir=str(p)))
    content = (p / "app" / "crud" / "base.py").read_text()
    assert content.count("SOFT_DELETE_PATCH_APPLIED") == 1, (
        "CRUDBase patch must be applied at most once."
    )
    assert content.count("CRUDBase.delete = _sd_delete") == 1, (
        "CRUDBase.delete reassignment must not be duplicated."
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
