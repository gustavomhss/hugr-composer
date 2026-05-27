"""Tests for TOOL-008 add_multi_tenancy.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_multi_tenancy.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_multi_tenancy.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy
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
    project_dir = create_fixture_project(name="mt01_success")
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got {result.status}: {result.error}"


def test_files_created_exist() -> None:
    """T-02: Every path in files_created actually exists on disk."""
    project_dir = create_fixture_project(name="mt02_files_exist")
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_created:
        assert Path(path_str).exists(), f"Created file missing: {path_str}"


def test_files_modified_exist() -> None:
    """T-03: Every path in files_modified actually exists on disk."""
    project_dir = create_fixture_project(name="mt03_modified_exist")
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for path_str in result.files_modified:
        assert Path(path_str).exists(), f"Modified file missing: {path_str}"


def test_tenant_mixin_created() -> None:
    """CC-02: app/models/mixins.py contains TenantScopedMixin with tenant_id."""
    project_dir = create_fixture_project(name="mt04_mixin")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    mixin_file = project_dir / "app" / "models" / "mixins.py"
    assert mixin_file.exists(), "mixins.py not created"
    content = mixin_file.read_text()
    assert "TenantScopedMixin" in content
    assert "tenant_id" in content
    assert "declared_attr" in content


def test_tenant_model_created() -> None:
    """CC-01: app/models/tenant.py exists with Tenant model and constraints."""
    project_dir = create_fixture_project(name="mt05_tenant_model")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    tenant_file = project_dir / "app" / "models" / "tenant.py"
    assert tenant_file.exists(), "tenant.py not created"
    content = tenant_file.read_text()
    assert "class Tenant" in content
    assert "slug" in content
    assert "ck_tenants_status" in content
    assert "ck_tenants_slug_format" in content


def test_tenant_context_module_created() -> None:
    """CC-05: tenant_context.py has get/set/require_current_tenant."""
    project_dir = create_fixture_project(name="mt06_context")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    ctx_file = project_dir / "app" / "core" / "tenant_context.py"
    assert ctx_file.exists(), "tenant_context.py not created"
    content = ctx_file.read_text()
    assert "get_current_tenant" in content
    assert "set_current_tenant" in content
    assert "require_current_tenant" in content
    assert "ContextVar" in content


def test_tenant_filter_module_created() -> None:
    """CC-06: tenant_filter.py registers do_orm_execute listener."""
    project_dir = create_fixture_project(name="mt07_filter")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    filter_file = project_dir / "app" / "core" / "tenant_filter.py"
    assert filter_file.exists(), "tenant_filter.py not created"
    content = filter_file.read_text()
    assert "do_orm_execute" in content
    assert "with_loader_criteria" in content
    assert "skip_tenant_filter" in content
    assert "TenantScopedMixin" in content


def test_tenant_middleware_created() -> None:
    """CC-07: TenantMiddleware exists and handles free paths + header resolver."""
    project_dir = create_fixture_project(name="mt08_middleware")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    mw_file = project_dir / "app" / "api" / "middleware" / "tenant.py"
    assert mw_file.exists(), "tenant.py middleware not created"
    content = mw_file.read_text()
    assert "class TenantMiddleware" in content
    assert "TENANT_FREE_PATHS" in content
    assert "X-Tenant-ID" in content
    assert "set_current_tenant" in content


def test_model_inherits_mixin() -> None:
    """CC-03: Target business model inherits TenantScopedMixin."""
    project_dir = create_fixture_project(name="mt09_model_inherits")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "item.py"
    assert model_file.exists()
    content = model_file.read_text()
    assert "TenantScopedMixin" in content
    assert "class Item(TenantScopedMixin, Base)" in content


def test_model_has_composite_index() -> None:
    """CC-04: Tenant-scoped model has composite index (tenant_id, created_at)."""
    project_dir = create_fixture_project(name="mt10_index")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    model_file = project_dir / "app" / "models" / "item.py"
    content = model_file.read_text()
    assert "ix_items_tenant_created" in content
    assert "__table_args__" in content


def test_crud_patched_with_require_tenant() -> None:
    """CC-13: CRUD module gains create_tenant_scoped using require_current_tenant."""
    project_dir = create_fixture_project(name="mt11_crud")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "item.py"
    assert crud_file.exists()
    content = crud_file.read_text()
    assert "require_current_tenant" in content
    assert "create_tenant_scoped" in content


def test_tenant_crud_module_created() -> None:
    """CC-16: app/crud/tenant.py exists with full CRUD."""
    project_dir = create_fixture_project(name="mt12_tenant_crud")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    crud_file = project_dir / "app" / "crud" / "tenant.py"
    assert crud_file.exists(), "crud/tenant.py not created"
    content = crud_file.read_text()
    for fn in ("get_by_slug", "get", "create", "update", "list_tenants"):
        assert f"async def {fn}" in content, f"Missing function: {fn}"


def test_tenant_schemas_created() -> None:
    """CC-27: app/schemas/tenant.py has TenantCreate/TenantUpdate/TenantPublic."""
    project_dir = create_fixture_project(name="mt13_schemas")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    schema_file = project_dir / "app" / "schemas" / "tenant.py"
    assert schema_file.exists(), "schemas/tenant.py not created"
    content = schema_file.read_text()
    assert "TenantCreate" in content
    assert "TenantUpdate" in content
    assert "TenantPublic" in content


def test_tenant_routes_created() -> None:
    """CC-16: app/api/routes/tenant.py has POST, GET (list), GET (slug), PATCH."""
    project_dir = create_fixture_project(name="mt14_routes")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "tenant.py"
    assert routes_file.exists(), "api/routes/tenant.py not created"
    content = routes_file.read_text()
    assert "async def create_tenant" in content
    assert "async def list_tenants" in content
    assert "async def get_tenant" in content
    assert "async def update_tenant" in content


def test_tenant_routes_require_superuser() -> None:
    """CC-16: Tenant admin routes use CurrentSuperuser dep."""
    project_dir = create_fixture_project(name="mt15_superuser")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    routes_file = project_dir / "app" / "api" / "routes" / "tenant.py"
    content = routes_file.read_text()
    assert "CurrentSuperuser" in content


def test_main_imports_tenant_filter() -> None:
    """CC-06: main.py imports tenant_filter (side-effect import)."""
    project_dir = create_fixture_project(name="mt16_main_filter")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    assert "tenant_filter" in main_file.read_text()


def test_main_registers_tenant_middleware() -> None:
    """CC-07: main.py registers TenantMiddleware."""
    project_dir = create_fixture_project(name="mt17_main_mw")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    main_file = project_dir / "app" / "main.py"
    content = main_file.read_text()
    assert "TenantMiddleware" in content
    assert "add_middleware" in content


def test_migration_created() -> None:
    """CC-09: Alembic migration creates tenants table + tenant_id columns."""
    project_dir = create_fixture_project(name="mt18_migration")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*multi_tenancy*"))
    assert len(migration_files) >= 1, "No multi-tenancy migration file created"
    content = migration_files[0].read_text()
    assert "def upgrade" in content
    assert "def downgrade" in content
    assert "tenants" in content
    assert "tenant_id" in content
    assert "op.create_table" in content


def test_migration_has_backfill() -> None:
    """CC-09: Migration backfills existing rows to default tenant."""
    project_dir = create_fixture_project(name="mt19_backfill")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*multi_tenancy*"))
    content = migration_files[0].read_text()
    assert "default" in content
    assert "INSERT INTO tenants" in content


def test_migration_has_restrict_fk() -> None:
    """CC-11: Migration FK uses ON DELETE RESTRICT."""
    project_dir = create_fixture_project(name="mt20_restrict")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*multi_tenancy*"))
    content = migration_files[0].read_text()
    assert "RESTRICT" in content


def test_all_py_files_parse() -> None:
    """CC-21: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="mt21_parse_all")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-26 / QS: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="mt22_idempotent")
    r1 = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Second run should be no_op, got: {r2.status}"
    assert not r2.files_created, "Second run must create no files"
    assert not r2.files_modified, "Second run must modify no files"


def test_idempotent_project_still_parses() -> None:
    """After two runs the project must still be fully parseable."""
    project_dir = create_fixture_project(name="mt23_idempotent_parse")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="mt24_dry_run")
    before = {f: f.read_text() for f in _all_py_files(project_dir)}
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py_files(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="mt25_timing")
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0, "execution_time_ms should be positive"


# ---------------------------------------------------------------------------
# Regression tests for confirmed bugs (fix/ee-tenancy)
# ---------------------------------------------------------------------------

_MULTIWORD_MODELS = {
    "Warehouse": {"name": "str"},
    "VaccineLot": {"lot": "str"},
    "Shipment": {"code": "str"},
}


def test_multiword_model_all_patched() -> None:
    """BUG-1 regression: ALL models must receive TenantScopedMixin, including
    multiword names (e.g. VaccineLot in vaccinelot.py) whose filename-derived
    PascalCase guess would have been 'Vaccinelot' ≠ 'VaccineLot'.

    Before fix: only Shipment and Warehouse were patched; VaccineLot was
    silently skipped → cross-tenant data leak vector.
    After fix: every model file whose stem matches a route file and contains
    a Base subclass is patched regardless of how its class name capitalises.
    """
    project_dir = create_fixture_project(name="mt26_multiword", models=_MULTIWORD_MODELS)
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success: {result.error}"

    models_dir = project_dir / "app" / "models"
    skip = {"base", "user", "mixins", "tenant", "__init__"}
    unpatched = []
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        content = f.read_text()
        if "TenantScopedMixin" not in content:
            unpatched.append(f.name)

    assert not unpatched, (
        f"Models NOT patched with TenantScopedMixin (cross-tenant leak): {unpatched}"
    )


def test_table_args_inside_class_scope() -> None:
    """BUG-2 regression: __table_args__ must be an attribute of the model
    CLASS, not a module-level assignment.

    Before fix: textwrap.dedent stripped all indentation from the appended
    block, emitting __table_args__ at column 0 (module scope), where
    SQLAlchemy ignores it — the composite index was never created.
    After fix: __table_args__ lands at 4-space indent inside the class body.
    """
    project_dir = create_fixture_project(name="mt27_class_scope", models=_MULTIWORD_MODELS)
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))

    models_dir = project_dir / "app" / "models"
    skip = {"base", "user", "mixins", "tenant", "__init__"}
    module_scope_violations = []
    missing_class_scope = []

    for f in sorted(models_dir.glob("*.py")):
        if f.stem in skip:
            continue
        content = f.read_text()
        if "TenantScopedMixin" not in content:
            continue

        tree = ast.parse(content)

        # Must NOT be at module scope
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "__table_args__":
                        module_scope_violations.append(f.name)

        # Must be inside a class that inherits TenantScopedMixin
        found_in_class = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            base_ids = [
                b.id if isinstance(b, ast.Name) else (b.attr if isinstance(b, ast.Attribute) else "")
                for b in node.bases
            ]
            if "TenantScopedMixin" not in base_ids:
                continue
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id == "__table_args__":
                            found_in_class = True
        if not found_in_class:
            missing_class_scope.append(f.name)

    assert not module_scope_violations, (
        f"__table_args__ at MODULE scope (index not registered): {module_scope_violations}"
    )
    assert not missing_class_scope, (
        f"__table_args__ missing from class body: {missing_class_scope}"
    )


def test_tenant_router_registered_in_routes_init() -> None:
    """BUG-3 regression: tenant router must be registered in app/routes/__init__.py.

    Before fix: app/api/routes/tenant.py was created but never included in
    api_router → the /tenants endpoints were unreachable.
    After fix: routes/__init__.py gains an include_router(tenant_router) call.
    """
    project_dir = create_fixture_project(name="mt28_routes_init")
    add_multi_tenancy(ToolInput(project_dir=str(project_dir)))

    routes_init = project_dir / "app" / "routes" / "__init__.py"
    assert routes_init.exists(), "app/routes/__init__.py not found"
    content = routes_init.read_text()
    assert "tenant_router" in content, (
        "tenant_router not imported in routes/__init__.py — /tenants endpoints unreachable"
    )
    assert "include_router(tenant_router)" in content, (
        "api_router.include_router(tenant_router) not called — /tenants endpoints unreachable"
    )


def test_multiword_boot() -> None:
    """BUG-1+2+3 integration: a project with multiword models must boot cleanly
    after multi-tenancy is applied (from app.main import app succeeds).
    """
    import os
    import subprocess

    project_dir = create_fixture_project(name="mt29_multiword_boot", models=_MULTIWORD_MODELS)
    result = add_multi_tenancy(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(project_dir)
    env["SECRET_KEY"] = "ci-test-secret-key-must-be-32-chars-long!!!"
    env["ENVIRONMENT"] = "local"
    env["RATE_LIMITING_ENABLED"] = "false"

    proc = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('BOOT OK')"],
        cwd=str(project_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, (
        f"Boot failed after multi-tenancy applied to multiword-model project.\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr[:1000]}"
    )
    assert "BOOT OK" in proc.stdout


# ---------------------------------------------------------------------------
# Standalone runner (fallback when pytest is unavailable)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_exist,
        test_files_modified_exist,
        test_tenant_mixin_created,
        test_tenant_model_created,
        test_tenant_context_module_created,
        test_tenant_filter_module_created,
        test_tenant_middleware_created,
        test_model_inherits_mixin,
        test_model_has_composite_index,
        test_crud_patched_with_require_tenant,
        test_tenant_crud_module_created,
        test_tenant_schemas_created,
        test_tenant_routes_created,
        test_tenant_routes_require_superuser,
        test_main_imports_tenant_filter,
        test_main_registers_tenant_middleware,
        test_migration_created,
        test_migration_has_backfill,
        test_migration_has_restrict_fk,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_multiword_model_all_patched,
        test_table_args_inside_class_scope,
        test_tenant_router_registered_in_routes_init,
        test_multiword_boot,
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
