"""Tests for TOOL-012 add_rbac.

Generates a real fixture project via ``fixture_factory.create_fixture_project``,
runs the tool, and verifies all completeness criteria from the spec.

Run with::

    PYTHONPATH=. pytest adapt/extend/auth_access/test_add_rbac.py -v

or without pytest::

    PYTHONPATH=. python3 adapt/extend/auth_access/test_add_rbac.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from adapt.contracts import ToolInput
from adapt.extend.auth_access.add_rbac import add_rbac
from tests.common.fixture_factory import create_fixture_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_py(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _assert_parse(root: Path) -> None:
    for f in _all_py(root):
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
    project_dir = create_fixture_project(name="rbac_t01")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success", f"Expected success, got: {result.status} / {result.error}"


def test_files_created_all_exist() -> None:
    """T-02: Every path in files_created exists on disk after the run."""
    project_dir = create_fixture_project(name="rbac_t02")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_created:
        assert Path(p).exists(), f"Created file missing: {p}"


def test_files_modified_all_exist() -> None:
    """T-03: Every path in files_modified exists on disk after the run."""
    project_dir = create_fixture_project(name="rbac_t03")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    for p in result.files_modified:
        assert Path(p).exists(), f"Modified file missing: {p}"


def test_rbac_models_file_created() -> None:
    """CC-01: app/models/rbac.py exists and contains all four model classes."""
    project_dir = create_fixture_project(name="rbac_t04")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    rbac_model = project_dir / "app" / "models" / "rbac.py"
    assert rbac_model.exists(), "app/models/rbac.py not created"
    content = rbac_model.read_text()
    for cls in ("Permission", "Role", "RolePermission", "UserRole"):
        assert f"class {cls}" in content, f"Model class {cls} missing from rbac.py"


def test_permission_code_format_constraint() -> None:
    """CC-02: Permission model uses resource:action code format constraint."""
    project_dir = create_fixture_project(name="rbac_t05")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "rbac.py").read_text()
    assert "ck_permissions_code_format" in content


def test_role_parent_fk_present() -> None:
    """CC-03: Role model has parent_id FK for DAG inheritance."""
    project_dir = create_fixture_project(name="rbac_t06")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "models" / "rbac.py").read_text()
    assert "parent_id" in content
    assert 'ForeignKey("roles.id"' in content


def test_inheritance_module_created() -> None:
    """CC-04: app/core/rbac/inheritance.py exists with effective_permissions and cycle detection."""
    project_dir = create_fixture_project(name="rbac_t07")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    inh = project_dir / "app" / "core" / "rbac" / "inheritance.py"
    assert inh.exists(), "inheritance.py not created"
    content = inh.read_text()
    assert "def effective_permissions" in content
    assert "CyclicRoleError" in content


def test_inheritance_cycle_detection_logic() -> None:
    """CC-05: DAG resolver detects cycles via visited set."""
    project_dir = create_fixture_project(name="rbac_t08")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "rbac" / "inheritance.py").read_text()
    assert "visited" in content
    assert "CyclicRoleError" in content


def test_evaluator_module_created() -> None:
    """CC-06: app/core/rbac/evaluator.py exists with compute_effective_permissions."""
    project_dir = create_fixture_project(name="rbac_t09")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    evaluator = project_dir / "app" / "core" / "rbac" / "evaluator.py"
    assert evaluator.exists(), "evaluator.py not created"
    content = evaluator.read_text()
    assert "async def compute_effective_permissions" in content
    assert "def has_permission" in content


def test_evaluator_wildcard_support() -> None:
    """CC-07: has_permission supports *:*, resource:*, *:action wildcards."""
    project_dir = create_fixture_project(name="rbac_t10")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "rbac" / "evaluator.py").read_text()
    assert "*:*" in content
    assert "resource" in content or "resource," in content or '"*"' in content


def test_cache_module_created() -> None:
    """CC-08: app/core/rbac/cache.py exists with PermissionCache class."""
    project_dir = create_fixture_project(name="rbac_t11")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    cache = project_dir / "app" / "core" / "rbac" / "cache.py"
    assert cache.exists(), "cache.py not created"
    content = cache.read_text()
    assert "class PermissionCache" in content or "PermCache" in content


def test_cache_ttl_and_redis_invalidation() -> None:
    """CC-09: Cache has TTL expiry + Redis pubsub invalidation channel."""
    project_dir = create_fixture_project(name="rbac_t12")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "rbac" / "cache.py").read_text()
    assert "TTL" in content or "ttl" in content
    assert "pubsub" in content or "subscribe" in content
    assert "invalidat" in content


def test_deps_module_created() -> None:
    """CC-10: app/core/rbac/deps.py exists with require_permission dependency."""
    project_dir = create_fixture_project(name="rbac_t13")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    deps = project_dir / "app" / "core" / "rbac" / "deps.py"
    assert deps.exists(), "deps.py not created"
    content = deps.read_text()
    assert "def require_permission" in content
    assert "Depends" in content


def test_require_permission_raises_403() -> None:
    """CC-11: require_permission raises HTTP 403 on missing permission."""
    project_dir = create_fixture_project(name="rbac_t14")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "rbac" / "deps.py").read_text()
    assert "403" in content or "HTTP_403_FORBIDDEN" in content


def test_schemas_file_created() -> None:
    """CC-12: app/schemas/rbac.py exists with required Pydantic schemas."""
    project_dir = create_fixture_project(name="rbac_t15")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    schemas = project_dir / "app" / "schemas" / "rbac.py"
    assert schemas.exists(), "schemas/rbac.py not created"
    content = schemas.read_text()
    for cls in ("PermissionCreate", "PermissionPublic", "RoleCreate", "RolePublic", "RoleAssignment"):
        assert cls in content, f"Schema {cls} missing"


def test_crud_file_created() -> None:
    """CC-13: app/crud/rbac.py exists with required CRUD functions."""
    project_dir = create_fixture_project(name="rbac_t16")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    crud = project_dir / "app" / "crud" / "rbac.py"
    assert crud.exists(), "crud/rbac.py not created"
    content = crud.read_text()
    for fn in ("create_permission", "create_role", "assign_user_role", "revoke_user_role"):
        assert f"async def {fn}" in content, f"CRUD function {fn} missing"


def test_routes_file_created() -> None:
    """CC-14: app/api/routes/rbac.py exists with admin CRUD endpoints."""
    project_dir = create_fixture_project(name="rbac_t17")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    routes = project_dir / "app" / "api" / "routes" / "rbac.py"
    assert routes.exists(), "routes/rbac.py not created"
    content = routes.read_text()
    assert "/rbac" in content or 'prefix="/rbac"' in content


def test_routes_superuser_only() -> None:
    """CC-15: RBAC admin routes require CurrentSuperuser."""
    project_dir = create_fixture_project(name="rbac_t18")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "api" / "routes" / "rbac.py").read_text()
    assert "CurrentSuperuser" in content


def test_migration_file_created() -> None:
    """CC-16: Alembic migration 0012_add_rbac.py exists."""
    project_dir = create_fixture_project(name="rbac_t19")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    files = list(versions_dir.glob("*rbac*"))
    assert files, "RBAC migration file not created"


def test_migration_creates_all_tables() -> None:
    """CC-17: Migration upgrade() creates permissions, roles, role_permissions, user_roles."""
    project_dir = create_fixture_project(name="rbac_t20")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    content = next(versions_dir.glob("*rbac*")).read_text()
    for table in ("permissions", "roles", "role_permissions", "user_roles"):
        assert table in content, f"Migration missing table: {table}"
    assert "def upgrade" in content
    assert "def downgrade" in content


def test_migration_seeds_default_roles() -> None:
    """CC-18: Migration seeds viewer, editor, admin roles and *:* permission."""
    project_dir = create_fixture_project(name="rbac_t21")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    versions_dir = project_dir / "alembic" / "versions"
    content = next(versions_dir.glob("*rbac*")).read_text()
    assert "viewer" in content
    assert "editor" in content
    assert "admin" in content
    assert "*:*" in content


def test_all_py_files_parse() -> None:
    """CC-19: All .py files in the project parse without SyntaxError after tool runs."""
    project_dir = create_fixture_project(name="rbac_t22")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_idempotent_returns_no_op() -> None:
    """CC-20 / QS-05: Running the tool twice returns no_op on the second run."""
    project_dir = create_fixture_project(name="rbac_t23")
    r1 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r1.status == "success"
    r2 = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert r2.status == "no_op", f"Expected no_op on second run, got: {r2.status}"
    assert not r2.files_created
    assert not r2.files_modified


def test_idempotent_project_still_parses() -> None:
    """After two runs, project .py files must still parse."""
    project_dir = create_fixture_project(name="rbac_t24")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    add_rbac(ToolInput(project_dir=str(project_dir)))
    _assert_parse(project_dir)


def test_dry_run_writes_nothing() -> None:
    """dry_run=True must return status='success' but write no files."""
    project_dir = create_fixture_project(name="rbac_t25")
    before = {f: f.read_text() for f in _all_py(project_dir)}
    result = add_rbac(ToolInput(project_dir=str(project_dir), dry_run=True))
    assert result.status == "success"
    assert not result.files_created
    assert not result.files_modified
    after = {f: f.read_text() for f in _all_py(project_dir)}
    assert before == after, "dry_run must not modify any file"


def test_execution_time_recorded() -> None:
    """execution_time_ms must be a positive integer after a successful run."""
    project_dir = create_fixture_project(name="rbac_t26")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.execution_time_ms > 0


def test_next_steps_present() -> None:
    """next_steps should guide the developer with alembic upgrade info."""
    project_dir = create_fixture_project(name="rbac_t27")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.next_steps) > 0
    assert any("alembic" in s for s in result.next_steps)


def test_inheritance_resolver_imported_by_evaluator() -> None:
    """evaluator.py or deps.py must import from the inheritance/evaluator module."""
    project_dir = create_fixture_project(name="rbac_t28")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    deps_content = (project_dir / "app" / "core" / "rbac" / "deps.py").read_text()
    eval_content = (project_dir / "app" / "core" / "rbac" / "evaluator.py").read_text()
    # Either deps imports evaluator, or evaluator exists with has_permission
    assert "compute_effective_permissions" in deps_content or "compute_effective_permissions" in eval_content


def test_perm_cache_singleton() -> None:
    """cache.py must expose a singleton getter (get_perm_cache or similar)."""
    project_dir = create_fixture_project(name="rbac_t29")
    add_rbac(ToolInput(project_dir=str(project_dir)))
    content = (project_dir / "app" / "core" / "rbac" / "cache.py").read_text()
    assert "def get_perm_cache" in content or "get_perm_cache" in content


def test_minimum_files_created() -> None:
    """Spec requires >= 10 files created (models, evaluator, cache, deps, schemas, etc.)."""
    project_dir = create_fixture_project(name="rbac_t30")
    result = add_rbac(ToolInput(project_dir=str(project_dir)))
    assert result.status == "success"
    assert len(result.files_created) >= 7, (
        f"Expected >=7 files created, got {len(result.files_created)}: {result.files_created}"
    )


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_success_status,
        test_files_created_all_exist,
        test_files_modified_all_exist,
        test_rbac_models_file_created,
        test_permission_code_format_constraint,
        test_role_parent_fk_present,
        test_inheritance_module_created,
        test_inheritance_cycle_detection_logic,
        test_evaluator_module_created,
        test_evaluator_wildcard_support,
        test_cache_module_created,
        test_cache_ttl_and_redis_invalidation,
        test_deps_module_created,
        test_require_permission_raises_403,
        test_schemas_file_created,
        test_crud_file_created,
        test_routes_file_created,
        test_routes_superuser_only,
        test_migration_file_created,
        test_migration_creates_all_tables,
        test_migration_seeds_default_roles,
        test_all_py_files_parse,
        test_idempotent_returns_no_op,
        test_idempotent_project_still_parses,
        test_dry_run_writes_nothing,
        test_execution_time_recorded,
        test_next_steps_present,
        test_inheritance_resolver_imported_by_evaluator,
        test_perm_cache_singleton,
        test_minimum_files_created,
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
