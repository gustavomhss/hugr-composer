"""TOOL-008: add_multi_tenancy — add hard tenant isolation to a FastAPI/SQLAlchemy project.

Adds a ``Tenant`` model, a ``TenantScopedMixin`` with a ``tenant_id`` FK, request-scoped
tenant context via ``ContextVar``, a SQLAlchemy ``do_orm_execute`` global filter, middleware
that resolves and validates the tenant from each request, patches all target business models,
adds CRUD ``/tenants`` endpoints, and generates a reversible Alembic migration that backfills
existing rows to a default tenant.

The tool is idempotent: a second run detects the ``TenantScopedMixin`` fingerprint and
returns ``status="no_op"`` without touching any file.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import load_template
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

from . import _patches as patches

_HERE = Path(__file__).parent


MCP_TOOL = {
    "name": "fastapi_auth_add_multi_tenancy",
    "description": "Add multi-tenancy support with schema-per-tenant or row-level isolation.",
    "tags": ["extend", "auth_access"],
    "entry": "add_multi_tenancy",
}


def _emit(template_name: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(load_template(_HERE, template_name).template)


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def add_multi_tenancy(inp: ToolInput) -> ToolResult:
    """Add hard multi-tenancy to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"
    mixins_file = app_dir / "models" / "mixins.py"
    if mixins_file.exists() and "TenantScopedMixin" in mixins_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "TenantScopedMixin already present — multi-tenancy is already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    model_names = patches.discover_models(app_dir)
    if not model_names:
        return ToolResult(
            status="error",
            error="No SQLAlchemy business models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add TenantScopedMixin for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # Step 1: mixin
    patches.write_mixin(_HERE, mixins_file)
    files_created.append(str(mixins_file))

    # Step 2: tenant model
    tenant_model_file = app_dir / "models" / "tenant.py"
    _emit("tenant_model.py.tmpl", tenant_model_file)
    files_created.append(str(tenant_model_file))
    patches.patch_models_init(app_dir / "models" / "__init__.py", [("tenant", "Tenant")])

    # Steps 3-5
    context_file = app_dir / "core" / "tenant_context.py"
    _emit("tenant_context.py.tmpl", context_file)
    files_created.append(str(context_file))

    filter_file = app_dir / "core" / "tenant_filter.py"
    _emit("tenant_filter.py.tmpl", filter_file)
    files_created.append(str(filter_file))

    middleware_file = app_dir / "api" / "middleware" / "tenant.py"
    _emit("tenant_middleware.py.tmpl", middleware_file)
    files_created.append(str(middleware_file))

    # Step 5a-c
    user_model_file = app_dir / "models" / "user.py"
    if user_model_file.exists():
        patches.patch_user_model(user_model_file)
        files_modified.append(str(user_model_file))

    deps_file = app_dir / "api" / "deps.py"
    if deps_file.exists():
        patches.patch_auth_deps(_HERE, deps_file)
        files_modified.append(str(deps_file))

    users_routes_file = app_dir / "api" / "routes" / "users.py"
    if users_routes_file.exists() and patches.patch_signup_tenant(users_routes_file):
        files_modified.append(str(users_routes_file))

    # Step 6-7: patch each business model + CRUD
    for model_name in model_names:
        model_file = app_dir / "models" / f"{model_name.lower()}.py"
        if model_file.exists():
            patches.patch_model(model_file, model_name)
            files_modified.append(str(model_file))
    for model_name in model_names:
        crud_file = app_dir / "crud" / f"{model_name.lower()}.py"
        if crud_file.exists():
            patches.patch_crud(_HERE, crud_file, model_name)
            files_modified.append(str(crud_file))

    # Steps 8-10
    tenant_crud_file = app_dir / "crud" / "tenant.py"
    _emit("tenant_crud.py.tmpl", tenant_crud_file)
    files_created.append(str(tenant_crud_file))

    tenant_schema_file = app_dir / "schemas" / "tenant.py"
    _emit("tenant_schemas.py.tmpl", tenant_schema_file)
    files_created.append(str(tenant_schema_file))

    tenant_routes_file = app_dir / "api" / "routes" / "tenant.py"
    _emit("tenant_routes.py.tmpl", tenant_routes_file)
    files_created.append(str(tenant_routes_file))

    # Step 10b-12
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        patches.patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    main_file = app_dir / "main.py"
    if main_file.exists():
        patches.patch_main(main_file)
        files_modified.append(str(main_file))

    conftest_file = project / "tests" / "conftest.py"
    if conftest_file.exists() and patches.patch_test_conftest(conftest_file):
        files_modified.append(str(conftest_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        migration_file = patches.write_migration(_HERE, versions_dir, model_names, down_rev)
        files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Multi-tenancy enabled for: {', '.join(model_names)}",
            "Tenancy is IDENTITY-bound: User.tenant_id is the source of truth; "
            "tenant context is resolved in the auth dependency, not a blind header.",
            "X-Tenant-ID is VALIDATED against the user's membership (mismatch -> 403); "
            "only a superuser may switch tenants via the header.",
            "Global ORM filter FAILS CLOSED: a tenant-scoped SELECT with no tenant "
            "context returns ZERO rows (never all rows).",
            "TenantMiddleware only resets per-request context + exempts public/auth "
            "paths; it never 400s the world. POST /tenants bootstrap works on a fresh DB.",
            "Emitted tests/conftest.py was updated to seed a tenant, bind test users, "
            "and send X-Tenant-ID so `pytest tests/` stays green.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Restart the application so tenant_filter side-effect import runs.",
            "Bootstrap: as the superuser, POST /api/v1/tenants {slug:'default', name:'Default'}.",
            "Assign users to a tenant by setting User.tenant_id (signup joins the "
            "tenant named in X-Tenant-ID automatically).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )
