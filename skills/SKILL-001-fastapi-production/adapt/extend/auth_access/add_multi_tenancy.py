"""TOOL-008: add_multi_tenancy — add hard tenant isolation to a FastAPI/SQLAlchemy project.

Adds a ``Tenant`` model, a ``TenantScopedMixin`` with a ``tenant_id`` FK, request-scoped
tenant context via ``ContextVar``, a SQLAlchemy ``do_orm_execute`` global filter, middleware
that resolves and validates the tenant from each request, patches all target business models,
adds CRUD ``/tenants`` endpoints, and generates a reversible Alembic migration that backfills
existing rows to a default tenant.

The tool is idempotent: a second run detects the ``TenantScopedMixin`` fingerprint and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.auth_access.add_multi_tenancy import add_multi_tenancy

    result = add_multi_tenancy(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["...tenant.py", "...tenant_context.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_auth_add_multi_tenancy",
    "description": "Add multi-tenancy support with schema-per-tenant or row-level isolation.",
    "tags": ["extend", "auth_access"],
    "entry": "add_multi_tenancy",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_multi_tenancy(inp: ToolInput) -> ToolResult:
    """Add hard multi-tenancy to a FastAPI project.

    Reads the project at ``inp.project_dir``, writes/patches all files
    necessary for request-scoped tenant isolation.  Returns a ``ToolResult``
    describing every file created or modified.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    # --- Pre-flight: idempotency check ---
    mixins_file = app_dir / "models" / "mixins.py"
    if mixins_file.exists() and "TenantScopedMixin" in mixins_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["TenantScopedMixin already present — multi-tenancy is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Discover target models ---
    model_names = _discover_models(app_dir)
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

    # --- Step 1: TenantScopedMixin in mixins.py ---
    _write_mixin(mixins_file)
    files_created.append(str(mixins_file))

    # --- Step 2: Tenant model ---
    tenant_model_file = app_dir / "models" / "tenant.py"
    _write_tenant_model(tenant_model_file)
    files_created.append(str(tenant_model_file))

    # Register Tenant in app/models/__init__.py so metadata.create_all()
    # discovers its Table. Without this, tests using create_all() get
    # UndefinedTableError when querying the tenants table.
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("tenant", "Tenant")],
    )

    # --- Step 3: Tenant context (ContextVar) ---
    context_file = app_dir / "core" / "tenant_context.py"
    _write_tenant_context(context_file)
    files_created.append(str(context_file))

    # --- Step 4: Global ORM filter ---
    filter_file = app_dir / "core" / "tenant_filter.py"
    _write_tenant_filter(filter_file)
    files_created.append(str(filter_file))

    # --- Step 5: TenantMiddleware ---
    middleware_file = app_dir / "api" / "middleware" / "tenant.py"
    middleware_file.parent.mkdir(parents=True, exist_ok=True)
    _write_tenant_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # --- Step 5a: Bind tenancy to identity — add User.tenant_id ---
    user_model_file = app_dir / "models" / "user.py"
    if user_model_file.exists():
        _patch_user_model(user_model_file)
        files_modified.append(str(user_model_file))

    # --- Step 5b: Resolve+enforce tenant in the AUTH dependency ---
    deps_file = app_dir / "api" / "deps.py"
    if deps_file.exists():
        _patch_auth_deps(deps_file)
        files_modified.append(str(deps_file))

    # --- Step 5c: Make signup join the tenant named in X-Tenant-ID ---
    users_routes_file = app_dir / "api" / "routes" / "users.py"
    if users_routes_file.exists() and _patch_signup_tenant(users_routes_file):
        files_modified.append(str(users_routes_file))

    # --- Step 6: Patch each business model ---
    for model_name in model_names:
        model_file = app_dir / "models" / f"{model_name.lower()}.py"
        if model_file.exists():
            _patch_model(model_file, model_name)
            files_modified.append(str(model_file))

    # --- Step 7: Patch each CRUD module ---
    for model_name in model_names:
        crud_file = app_dir / "crud" / f"{model_name.lower()}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name)
            files_modified.append(str(crud_file))

    # --- Step 8: Write tenant CRUD module ---
    tenant_crud_file = app_dir / "crud" / "tenant.py"
    _write_tenant_crud(tenant_crud_file)
    files_created.append(str(tenant_crud_file))

    # --- Step 9: Write tenant schemas ---
    tenant_schema_file = app_dir / "schemas" / "tenant.py"
    _write_tenant_schemas(tenant_schema_file)
    files_created.append(str(tenant_schema_file))

    # --- Step 10: Write tenant routes ---
    tenant_routes_file = app_dir / "api" / "routes" / "tenant.py"
    _write_tenant_routes(tenant_routes_file)
    files_created.append(str(tenant_routes_file))

    # --- Step 10b: Register tenant router in app/routes/__init__.py ---
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    # --- Step 11: Patch main.py to register middleware + filter import ---
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 11b: Update emitted test fixtures so pytest stays GREEN ---
    # Seed a tenant, bind the test users to it, and inject X-Tenant-ID on
    # every request the test client makes.  Without this the emitted suite
    # would fail under identity-bound tenancy (users with no tenant_id).
    conftest_file = project / "tests" / "conftest.py"
    if conftest_file.exists() and _patch_test_conftest(conftest_file):
        files_modified.append(str(conftest_file))

    # --- Step 12: Alembic migration ---
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir, model_names)
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


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    ``metadata.create_all()`` relies on ``app/models/__init__.py`` importing
    every model module so that their Table definitions are attached to
    ``Base.metadata``.  New model files created by adapt tools MUST be
    registered here or tests that use ``create_all()`` will silently skip
    their tables.

    Args:
        models_init: Absolute path to ``app/models/__init__.py``.
        class_imports: List of ``(module_name, class_name)`` pairs, where
            ``module_name`` is the module under ``app.models`` (e.g.
            ``"tenant"``) and ``class_name`` is the class to import
            (e.g. ``"Tenant"``).
    """
    if not models_init.exists():
        return
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker in content:
            continue
        new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase business model names, excluding User/Base/Tenant/mixins.

    Only includes models where:
    1. The file contains at least one class directly inheriting from ``Base``
       (read from the AST — NOT derived from the filename).
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    The class name is taken directly from the AST, so multiword models whose
    file name is all-lowercase-no-underscore (e.g. ``vaccinelot.py`` →
    class ``VaccineLot``) are discovered correctly.  The old approach of
    guessing the PascalCase name from the stem (``"".join(w.capitalize() …)``)
    was wrong for those cases and caused them to be silently skipped.

    This avoids patching infrastructure files like ``mfa.py``, ``api_key.py``,
    or ``feature_flag.py`` (route is ``feature_flags.py``, not ``feature_flag.py``).

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item", "VaccineLot"]``).
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "tenant", "__init__"}
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    names = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if stem not in available_routes:
            continue
        # Read the ACTUAL class names from the AST instead of guessing from
        # the filename stem.  Filename-guessing breaks for multiword models
        # like VaccineLot (file: vaccinelot.py → stem: vaccinelot →
        # guessed: "Vaccinelot" ≠ "VaccineLot") — those would be silently
        # skipped, leaving them without tenant isolation (cross-tenant leak).
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        base_subclasses = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        # Only the class canonical for this file (name.lower() == stem): keeps
        # multiword models, skips multi-class files (e.g. websocket chat.py with
        # ChatRoom + ChatMessage) whose stem matches no class — which would
        # otherwise be patched inconsistently / with broken module paths.
        base_subclasses = [c for c in base_subclasses if c.lower() == stem]
        names.extend(base_subclasses)
    return sorted(names)


def _write_mixin(dest: Path) -> None:
    """Write or extend ``app/models/mixins.py`` with ``TenantScopedMixin``.

    If the file already exists (e.g. SoftDeleteMixin was added by
    add_soft_delete), the new class is APPENDed so existing mixins are
    preserved.  Duplicate imports are suppressed.

    Args:
        dest: Absolute path for the file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    new_imports = [
        "from __future__ import annotations",
        "import uuid",
        "from sqlalchemy import ForeignKey, Uuid",
        "from sqlalchemy.orm import Mapped, declared_attr, mapped_column",
    ]

    mixin_body = textwrap.dedent("""\

        class TenantScopedMixin:
            \"\"\"Add tenant_id FK to every business model for hard isolation.

            Inherit *before* Base::

                class Item(TenantScopedMixin, Base): ...

            Attributes:
                tenant_id: Non-nullable FK to tenants.id.  ON DELETE RESTRICT
                    ensures a tenant with live rows cannot be deleted.
            \"\"\"

            @declared_attr
            def tenant_id(cls) -> Mapped[uuid.UUID]:
                return mapped_column(
                    Uuid,
                    ForeignKey("tenants.id", ondelete="RESTRICT"),
                    nullable=False,
                    index=True,
                )
        """)

    if dest.exists():
        existing = dest.read_text()
        # Inject only the imports that are not already present
        lines_to_add = [imp for imp in new_imports if imp not in existing]
        if lines_to_add:
            # Insert after the module docstring / existing imports block
            existing = existing.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n"
        dest.write_text(existing + mixin_body)
    else:
        header = textwrap.dedent("""\
            \"\"\"Reusable SQLAlchemy mixins.\"\"\"

            from __future__ import annotations

            import uuid

            from sqlalchemy import ForeignKey, Uuid
            from sqlalchemy.orm import Mapped, declared_attr, mapped_column
            """)
        dest.write_text(header + mixin_body)


def _write_tenant_model(dest: Path) -> None:
    """Write ``app/models/tenant.py`` with the Tenant ORM model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"ORM model for Tenant.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import CheckConstraint, DateTime, String, Uuid, func
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class Tenant(Base):
            \"\"\"Tenant model for hard multi-tenant isolation.

            Attributes:
                id: UUID primary key.
                slug: URL-safe unique identifier (e.g. 'acme-corp').
                name: Human-readable display name.
                status: One of 'active', 'suspended', 'archived'.
                created_at: UTC creation timestamp.
            \"\"\"

            __tablename__ = "tenants"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False, index=True)
            name: Mapped[str] = mapped_column(String(255), nullable=False)
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="active"
            )
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            __table_args__ = (
                CheckConstraint(
                    "status IN ('active', 'suspended', 'archived')",
                    name="ck_tenants_status",
                ),
                CheckConstraint(
                    "length(slug) >= 1 AND length(slug) <= 63",
                    name="ck_tenants_slug_format",
                ),
            )
        """)
    dest.write_text(content)


def _write_tenant_context(dest: Path) -> None:
    """Write ``app/core/tenant_context.py`` with per-request ContextVar helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Request-scoped tenant context via ContextVar.

        Set once by TenantMiddleware at request ingress; read by CRUD helpers
        and the ORM auto-filter throughout the request lifecycle.

        Example::

            # In background jobs that scan all tenants:
            set_current_tenant(tenant_id)
            try:
                await process_tenant(session)
            finally:
                set_current_tenant(None)
        \"\"\"

        from __future__ import annotations

        import uuid
        from contextvars import ContextVar

        _current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar(
            "current_tenant_id", default=None
        )


        def set_current_tenant(tenant_id: uuid.UUID | None) -> None:
            \"\"\"Set the current request's tenant ID in context.

            Args:
                tenant_id: Tenant UUID, or None for system/unauthenticated context.
            \"\"\"
            _current_tenant_id.set(tenant_id)


        def get_current_tenant() -> uuid.UUID | None:
            \"\"\"Return the current tenant ID, or None if not set.

            Returns:
                Tenant UUID or None.
            \"\"\"
            return _current_tenant_id.get()


        def require_current_tenant() -> uuid.UUID:
            \"\"\"Return the current tenant ID, raising if not set.

            Returns:
                Tenant UUID.

            Raises:
                RuntimeError: If no tenant is in context (TenantContextMissing).
            \"\"\"
            tid = _current_tenant_id.get()
            if tid is None:
                raise RuntimeError(
                    "TenantContextMissing: no tenant in context. "
                    "Either the request did not pass through TenantMiddleware, "
                    "or this code path runs outside a tenant scope."
                )
            return tid
        """)
    dest.write_text(content)


def _write_tenant_filter(dest: Path) -> None:
    """Write ``app/core/tenant_filter.py`` with the do_orm_execute listener.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Global tenant query filter via SQLAlchemy session event.

        Import this module once at application startup (main.py) to activate
        the filter.  Every SELECT against a TenantScopedMixin model will
        automatically receive a ``WHERE tenant_id = :current_tenant_id``
        predicate unless the execution option ``skip_tenant_filter=True`` is set.

        FAIL-CLOSED CONTRACT
        --------------------
        If no tenant is present in the request context, a tenant-scoped SELECT
        returns ZERO rows — it does NOT skip the filter. Skipping would FAIL
        OPEN and leak every tenant's data to a context-less query. The ONLY
        escape hatch is the explicit ``skip_tenant_filter=True`` execution
        option, reserved for trusted admin/system paths (e.g. listing tenants).

        Example::

            # main.py — side-effect import (no symbol needed)
            import app.core.tenant_filter  # noqa: F401
        \"\"\"

        from sqlalchemy import event, false
        from sqlalchemy.orm import Session, with_loader_criteria

        from app.core.tenant_context import get_current_tenant
        from app.models.mixins import TenantScopedMixin


        @event.listens_for(Session, "do_orm_execute")
        def _enforce_tenant_filter(execute_state) -> None:
            \"\"\"Inject WHERE tenant_id = current_tenant for every default SELECT.

            Args:
                execute_state: SQLAlchemy ORM execute state object.

            Skip by passing execution option ``skip_tenant_filter=True``::

                stmt = select(Item).execution_options(skip_tenant_filter=True)
            \"\"\"
            if not execute_state.is_select:
                return
            if execute_state.execution_options.get("skip_tenant_filter"):
                return

            tenant_id = get_current_tenant()
            if tenant_id is None:
                # FAIL CLOSED: no tenant context -> a tenant-scoped query must
                # return nothing rather than every tenant's rows. We inject an
                # always-false predicate (not a no-op return).
                execute_state.statement = execute_state.statement.options(
                    with_loader_criteria(
                        TenantScopedMixin,
                        lambda cls: false(),
                        include_aliases=True,
                    )
                )
                return

            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    TenantScopedMixin,
                    lambda cls: cls.tenant_id == tenant_id,
                    include_aliases=True,
                )
            )


        @event.listens_for(Session, "before_flush")
        def _auto_populate_tenant_id(session, flush_context, instances) -> None:
            \"\"\"Auto-populate tenant_id on INSERT for every TenantScopedMixin row.

            The CRUD code typically does ``session.add(Model(**data))`` without
            an explicit tenant_id; the middleware has already set the
            current_tenant_id ContextVar, so we inject it here right before the
            flush hits the database. This means route handlers NEVER need to
            pass tenant_id — the framework does it invisibly.

            Skipped when there is no current tenant (e.g. system/background job)
            or when the caller explicitly set tenant_id already.
            \"\"\"
            tenant_id = get_current_tenant()
            if tenant_id is None:
                return
            for obj in session.new:
                if isinstance(obj, TenantScopedMixin) and getattr(obj, "tenant_id", None) is None:
                    obj.tenant_id = tenant_id
        """)
    dest.write_text(content)


def _write_tenant_middleware(dest: Path) -> None:
    """Write ``app/api/middleware/tenant.py`` with TenantMiddleware.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Per-request tenant-context lifecycle middleware.

        IMPORTANT — security model
        --------------------------
        This middleware does NOT decide which tenant a request belongs to and
        it NEVER rejects a request on its own. Tenant authority is bound to
        IDENTITY and resolved in the auth dependency (see
        ``app.api.deps.get_current_user`` / ``resolve_tenant``), AFTER the
        caller has been authenticated. A blind, header-driven pre-auth
        middleware that 400s every request without ``X-Tenant-ID`` is both
        insecure (any caller who knows a slug operates in that tenant) and
        breaks every auth/public/CRUD route + bootstrap.

        What this middleware DOES:
          * Reset the per-request tenant ContextVar to ``None`` at ingress so
            tenant context never leaks across requests sharing a worker.
          * Clear it again on the way out (defence in depth).

        The X-Tenant-ID header is read and validated downstream, in the auth
        dependency, against the authenticated user's membership.

        TENANT_FREE_PATHS documents the public/auth/util/bootstrap routes that
        legitimately run with NO tenant context (the auth dependency exempts
        the same set by simply not requiring a tenant there).
        \"\"\"

        from __future__ import annotations

        from fastapi import Request
        from starlette.middleware.base import BaseHTTPMiddleware

        from app.core.tenant_context import set_current_tenant

        # Public / auth / utility / bootstrap paths that operate with NO tenant.
        # These are the routes that must work before (or without) a tenant
        # context: login, self-service signup, "who am I", health, docs, and
        # the POST /tenants bootstrap endpoint (a fresh DB has no tenant yet).
        TENANT_FREE_PATHS = {
            "/api/v1/login/access-token",
            "/api/v1/login/test-token",
            "/api/v1/users/signup",
            "/api/v1/users/me",
            "/api/v1/auth/register",
            "/health",
            "/healthz",
            "/readyz",
            "/startupz",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/openapi.json",
        }

        # Prefixes whose every sub-path is tenant-free (utils, login flows).
        TENANT_FREE_PREFIXES = (
            "/api/v1/login",
            "/api/v1/utils",
        )


        def is_tenant_free_path(path: str) -> bool:
            \"\"\"Return True if *path* legitimately runs with no tenant context.\"\"\"
            if path in TENANT_FREE_PATHS:
                return True
            return any(path.startswith(p) for p in TENANT_FREE_PREFIXES)


        class TenantMiddleware(BaseHTTPMiddleware):
            \"\"\"Reset/clear the per-request tenant ContextVar around each request.

            Args:
                app: ASGI application.
                resolver: Retained for backward compatibility / configurability.
                    The authoritative tenant is resolved from IDENTITY in the
                    auth dependency regardless of this value.
                    'header' (default) means the auth dep honours X-Tenant-ID for
                    superuser tenant-switching; 'subdomain'/'jwt' are reserved.
            \"\"\"

            def __init__(self, app, resolver: str = "header") -> None:
                super().__init__(app)
                self.resolver = resolver

            async def dispatch(self, request: Request, call_next):
                \"\"\"Reset tenant context, run the request, then clear context.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next ASGI handler.

                Returns:
                    The downstream HTTP response. This middleware never short-
                    circuits with its own error response — authorization is the
                    auth dependency's job.
                \"\"\"
                # Always start each request with a clean, tenant-less context.
                # The auth dependency sets the real tenant after authenticating.
                set_current_tenant(None)
                try:
                    return await call_next(request)
                finally:
                    # Defence in depth: never let a tenant id outlive the request.
                    set_current_tenant(None)
        """)
    dest.write_text(content)


def _patch_user_model(user_file: Path) -> None:
    """Add a nullable ``tenant_id`` FK column to the User model (identity binding).

    Tenancy is bound to identity: the authenticated user's ``tenant_id`` is the
    source of truth for tenant context.  The column is NULLABLE on purpose:

      * ``None`` == a global / system / not-yet-assigned account (e.g. the very
        first superuser, who must be able to create the first tenant on a fresh
        DB — the bootstrap case).
      * A non-null value binds the user to exactly one tenant.

    The User model deliberately does NOT inherit ``TenantScopedMixin`` (which is
    NOT-NULL and would itself be tenant-filtered) — users are looked up during
    authentication, before any tenant context exists.

    Idempotent: a second run detects ``tenant_id`` and no-ops.

    Args:
        user_file: Path to ``app/models/user.py``.
    """
    src = user_file.read_text()
    if "tenant_id" in src:
        return

    # Ensure ForeignKey is imported from sqlalchemy.
    if "ForeignKey" not in src:
        import re as _re
        _multi = _re.search(r"(from sqlalchemy import\s*\()", src)
        if _multi:
            src = src[: _multi.end()] + "\n    ForeignKey," + src[_multi.end():]
        elif "from sqlalchemy import" in src:
            src = src.replace("from sqlalchemy import", "from sqlalchemy import ForeignKey,", 1)

    # Insert the column right after the primary key line so it lands inside the
    # class body at the correct indentation regardless of the other columns.
    pk_marker = "id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)"
    tenant_col = (
        "\n    # Identity-bound tenancy: NULL == global/system/unassigned (bootstrap)."
        "\n    tenant_id: Mapped[uuid.UUID | None] = mapped_column("
        "\n        Uuid, ForeignKey(\"tenants.id\", ondelete=\"RESTRICT\"), nullable=True, index=True"
        "\n    )"
    )
    if pk_marker in src:
        src = src.replace(pk_marker, pk_marker + tenant_col, 1)
        candidate = src
        _verify_attr_in_class(candidate, "User", "tenant_id")
        user_file.write_text(candidate)
        return

    # Fallback: append the column as a class-level statement after the class def.
    import re as _re
    m = _re.search(r"class User\([^)]*\):\n", src)
    if not m:
        return
    # Find indentation of first attribute by scanning the class body.
    insert_at = m.end()
    src = src[:insert_at] + "    " + tenant_col.lstrip() + "\n" + src[insert_at:]
    _verify_attr_in_class(src, "User", "tenant_id")
    user_file.write_text(src)


def _verify_attr_in_class(src: str, class_name: str, attr: str) -> None:
    """Assert that *attr* is an annotated/assigned attribute of *class_name*.

    Args:
        src: Python source to check.
        class_name: Target class.
        attr: Attribute name that must live in the class body.

    Raises:
        RuntimeError: If *attr* is not found inside the class body.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                target = None
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    target = item.target.id
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name):
                            target = t.id
                if target == attr:
                    return
    raise RuntimeError(
        f"{attr} not found inside class {class_name} after patching — tool bug."
    )


def _patch_auth_deps(deps_file: Path) -> None:
    """Resolve + enforce the request tenant inside the AUTH dependency.

    This is the heart of the secure design.  After ``get_current_user`` has
    authenticated the caller, we derive the tenant from the AUTHENTICATED user
    (NOT from a blind header) and set the request-scoped tenant context:

      * The user's ``tenant_id`` is the source of truth.
      * If ``X-Tenant-ID`` is supplied it is VALIDATED against the user's
        membership; a mismatch is ``403`` — EXCEPT a superuser, who MAY switch
        to any active tenant via the header.
      * A user with ``tenant_id is None`` and no header keeps a tenant-less
        context.  Because the global filter FAILS CLOSED, such a request reads
        ZERO tenant-scoped rows — it cannot leak another tenant's data.

    Idempotent: detects ``resolve_tenant`` and no-ops.

    Args:
        deps_file: Path to ``app/api/deps.py``.
    """
    src = deps_file.read_text()
    if "resolve_tenant" in src:
        return

    # 1. Make get_current_user take the Request so it can read X-Tenant-ID, and
    #    call resolve_tenant before returning the user.
    if "from fastapi import" in src and "Request" not in src.split("\n\n", 1)[0]:
        import re as _re
        src = _re.sub(
            r"from fastapi import ([^\n]+)",
            lambda m: (
                f"from fastapi import {m.group(1)}"
                if "Request" in m.group(1)
                else f"from fastapi import Request, {m.group(1)}"
            ),
            src,
            count=1,
        )

    # Inject `request: Request` as the first param of get_current_user and a
    # `await resolve_tenant(...)` call right before it returns the user.
    src = src.replace(
        "async def get_current_user(\n    session: SessionDep,",
        "async def get_current_user(\n    request: Request,\n    session: SessionDep,",
        1,
    )
    # Place the tenant resolution right before the final `return user`.
    src = src.replace(
        "    if user is None or not user.is_active:\n        raise _CREDENTIALS_ERROR\n\n    return user",
        "    if user is None or not user.is_active:\n        raise _CREDENTIALS_ERROR\n\n"
        "    # Identity-bound tenancy: set the request tenant context from the\n"
        "    # AUTHENTICATED user (and validate any X-Tenant-ID against membership).\n"
        "    await resolve_tenant(session, user, request)\n\n    return user",
        1,
    )

    helper = textwrap.dedent('''

        # ---------------------------------------------------------------------------
        # Identity-bound tenant resolution — added by add_multi_tenancy tool
        # ---------------------------------------------------------------------------
        from sqlalchemy import select as _mt_select  # noqa: E402

        from app.core.tenant_context import set_current_tenant as _mt_set_tenant  # noqa: E402
        from app.models.tenant import Tenant as _MTTenant  # noqa: E402


        async def resolve_tenant(session, user: "User", request: "Request") -> None:
            """Bind the request to a tenant, derived from the authenticated user.

            Security contract:
              * The user's ``tenant_id`` is authoritative.
              * ``X-Tenant-ID`` (a tenant *slug*) is only a hint and is VALIDATED:
                  - normal user: header slug must resolve to the user's own
                    tenant, else ``403`` (no cross-tenant access by knowing a slug);
                  - superuser: header slug may name ANY active tenant -> switches
                    context to it (admin acting within a tenant).
              * No tenant + no header -> tenant-less context. The global filter
                FAILS CLOSED, so tenant-scoped reads return nothing.

            Args:
                session: Active async DB session (override-aware in tests).
                user: The authenticated user.
                request: The incoming request (for the X-Tenant-ID header).

            Raises:
                HTTPException 403: header names a tenant the user may not access.
                HTTPException 400: header names an unknown/inactive tenant.
            """
            header_slug = request.headers.get("X-Tenant-ID")

            async def _lookup(slug: str):
                stmt = (
                    _mt_select(_MTTenant)
                    .where(_MTTenant.slug == slug)
                    .execution_options(skip_tenant_filter=True)
                )
                return (await session.execute(stmt)).scalar_one_or_none()

            # Superuser may switch into any active tenant named by the header.
            if user.is_superuser and header_slug:
                tenant = await _lookup(header_slug)
                if tenant is None or tenant.status != "active":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Unknown or inactive tenant",
                    )
                _mt_set_tenant(tenant.id)
                return

            # Normal user (and superuser without a switch header): bind to the
            # user's own tenant.
            if user.tenant_id is not None:
                if header_slug:
                    tenant = await _lookup(header_slug)
                    # The header, if present, MUST match the user's own tenant.
                    if tenant is None or tenant.id != user.tenant_id:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="X-Tenant-ID does not match your tenant membership",
                        )
                _mt_set_tenant(user.tenant_id)
                return

            # No membership and not a superuser switch: leave context tenant-less.
            # The global filter fails closed, so tenant-scoped reads see nothing.
            _mt_set_tenant(None)
        ''')

    deps_file.write_text(src.rstrip("\n") + "\n" + helper)


def _patch_signup_tenant(users_file: Path) -> bool:
    """Make the public signup endpoint join the tenant named in ``X-Tenant-ID``.

    Self-service onboarding model: a new user who signs up with an
    ``X-Tenant-ID`` header becomes a member of THAT tenant (its ``tenant_id``
    is stamped on the row).  After signup the user is BOUND to that tenant and
    cannot later switch by changing the header (see ``resolve_tenant``).  No
    header -> a global/unassigned user (``tenant_id`` stays NULL).

    This keeps the standard signup -> login -> CRUD flow working under
    identity-bound tenancy without weakening isolation.

    Idempotent: detects the injected marker and no-ops.

    Returns:
        True if the file was modified, False otherwise.
    """
    src = users_file.read_text()
    if "_mt_signup_tenant" in src:
        return False
    # Only patch the canonical scaffold signup signature.
    sig = (
        "async def signup(\n"
        "    request: Request,\n"
        "    session: SessionDep,\n"
        "    body: UserCreate,\n"
        ") -> UserPublic:"
    )
    if sig not in src:
        # Signup shape differs from the scaffold; skip rather than corrupt it.
        return False

    # Ensure the helper imports exist (Request is already imported in users.py).
    if "from app.models.tenant import Tenant as _MTTenant" not in src:
        # Insert imports after the first import block (top of file, after docstring).
        marker = "from app.schemas.message import Message\n"
        helper_imports = (
            "from sqlalchemy import select as _mt_select\n"
            "from app.models.tenant import Tenant as _MTTenant\n"
        )
        if marker in src:
            src = src.replace(marker, marker + helper_imports, 1)
        else:
            src = helper_imports + src

    # Inject tenant resolution into the signup body, right where obj_in is built.
    anchor = "    obj_in = body.model_dump()\n    obj_in[\"hashed_password\"] = get_password_hash(obj_in.pop(\"password\"))"
    inject = (
        "    obj_in = body.model_dump()\n"
        "    obj_in[\"hashed_password\"] = get_password_hash(obj_in.pop(\"password\"))\n"
        "    # _mt_signup_tenant: bind the new user to the tenant named in X-Tenant-ID.\n"
        "    _mt_slug = request.headers.get(\"X-Tenant-ID\")\n"
        "    if _mt_slug:\n"
        "        _mt_stmt = (\n"
        "            _mt_select(_MTTenant)\n"
        "            .where(_MTTenant.slug == _mt_slug)\n"
        "            .execution_options(skip_tenant_filter=True)\n"
        "        )\n"
        "        _mt_tenant = (await session.execute(_mt_stmt)).scalar_one_or_none()\n"
        "        if _mt_tenant is not None and _mt_tenant.status == \"active\":\n"
        "            obj_in[\"tenant_id\"] = _mt_tenant.id"
    )
    if anchor not in src:
        return False
    src = src.replace(anchor, inject, 1)
    users_file.write_text(src)
    return True


def _patch_test_conftest(conftest_file: Path) -> bool:
    """Update the emitted ``tests/conftest.py`` so pytest stays GREEN.

    Under identity-bound tenancy the scaffold's fixtures would fail: their
    users have no ``tenant_id`` and the client sends no ``X-Tenant-ID``, so
    every tenant-scoped CRUD read returns zero rows and creates have no tenant.

    This patch:
      * seeds a ``Tenant`` (slug ``test-tenant``) in the ``session`` fixture;
      * stamps that tenant on the superuser and normal-user fixtures;
      * injects ``X-Tenant-ID: test-tenant`` as a default header on the test
        client so every request carries it (matching real usage).

    Idempotent: detects the marker and no-ops.

    Returns:
        True if modified, False otherwise.
    """
    src = conftest_file.read_text()
    if "_MT_TENANT_SLUG" in src:
        return False

    # 1. Module-level constant + import of Tenant model.
    if "from app.models.user import User" in src:
        src = src.replace(
            "from app.models.user import User",
            "from app.models.user import User\n"
            "from app.models.tenant import Tenant\n"
            "\n_MT_TENANT_SLUG = \"test-tenant\"",
            1,
        )
    else:
        src = src.replace(
            "from app.main import app",
            "from app.main import app\n"
            "from app.models.tenant import Tenant\n"
            "\n_MT_TENANT_SLUG = \"test-tenant\"",
            1,
        )

    # 2. Seed a tenant in the `session` fixture, right after create_all, and
    #    expose it via the session so token fixtures can read its id.
    create_all_anchor = (
        "    async with engine_test.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n\n"
        "    async with async_session_test() as sess:\n"
        "        yield sess"
    )
    create_all_replacement = (
        "    async with engine_test.begin() as conn:\n"
        "        await conn.run_sync(Base.metadata.create_all)\n\n"
        "    async with async_session_test() as sess:\n"
        "        # multi-tenancy: seed a tenant every test user belongs to.\n"
        "        import uuid as _mt_uuid\n"
        "        _mt_tenant = Tenant(\n"
        "            id=_mt_uuid.uuid4(), slug=_MT_TENANT_SLUG,\n"
        "            name=\"Test Tenant\", status=\"active\",\n"
        "        )\n"
        "        sess.add(_mt_tenant)\n"
        "        await sess.commit()\n"
        "        sess.info[\"mt_tenant_id\"] = _mt_tenant.id\n"
        "        yield sess"
    )
    if create_all_anchor in src:
        src = src.replace(create_all_anchor, create_all_replacement, 1)

    # 3. Stamp tenant_id on the superuser + normal-user fixtures.
    src = src.replace(
        "        is_active=True,\n        is_superuser=True,\n    )",
        "        is_active=True,\n        is_superuser=True,\n"
        "        tenant_id=session.info.get(\"mt_tenant_id\"),\n    )",
        1,
    )
    src = src.replace(
        "        is_active=True,\n        is_superuser=False,\n    )",
        "        is_active=True,\n        is_superuser=False,\n"
        "        tenant_id=session.info.get(\"mt_tenant_id\"),\n    )",
        1,
    )

    # 4. Make the client send X-Tenant-ID on every request by default.
    src = src.replace(
        "    transport = ASGITransport(app=app)\n"
        "    async with AsyncClient(transport=transport, base_url=\"http://test\") as ac:",
        "    transport = ASGITransport(app=app)\n"
        "    async with AsyncClient(\n"
        "        transport=transport, base_url=\"http://test\",\n"
        "        headers={\"X-Tenant-ID\": _MT_TENANT_SLUG},\n"
        "    ) as ac:",
        1,
    )

    conftest_file.write_text(src)
    return True


def _patch_model(model_file: Path, model_name: str) -> None:
    """Inject TenantScopedMixin into a model class and add composite index.

    The composite index ``__table_args__`` is appended INSIDE the class body
    (4-space indent) — NOT at module scope.  Previously ``textwrap.dedent``
    stripped all leading whitespace from the appended block, causing
    ``__table_args__`` to land at column 0 (module scope), which SQLAlchemy
    silently ignores; the index was never registered on the model.

    Args:
        model_file: Path to the model ``.py`` file.
        model_name: PascalCase class name (e.g. ``"Item"``).
    """
    src = model_file.read_text()
    if "TenantScopedMixin" in src:
        return

    table_name = model_name.lower() + "s"

    # Add import for TenantScopedMixin
    if "from app.models.mixins import TenantScopedMixin" not in src:
        src = src.replace(
            "from app.models.base import Base",
            "from app.models.base import Base\nfrom app.models.mixins import TenantScopedMixin",
        )

    # Add Index import if not present — handle both single-line and multi-line forms
    if "Index" not in src:
        import re as _re
        # Multi-line: from sqlalchemy import (
        #     Column,
        # )
        _multi = _re.search(r"(from sqlalchemy import\s*\()", src)
        if _multi:
            # Insert "Index,\n    " as the first item inside the parentheses
            src = src[: _multi.end()] + "\n    Index," + src[_multi.end():]
        elif "from sqlalchemy import" in src:
            # Single-line: from sqlalchemy import Column, String
            src = src.replace("from sqlalchemy import", "from sqlalchemy import Index,", 1)

    # Patch class declaration
    src = src.replace(
        "class " + model_name + "(Base):",
        "class " + model_name + "(TenantScopedMixin, Base):",
    )

    # Append composite index INSIDE the class body (4-space indent).
    # Do NOT use textwrap.dedent here — it would strip the leading whitespace
    # and emit __table_args__ at module scope (column 0), where SQLAlchemy
    # ignores it and the index is never registered on the model.
    index_block = (
        "\n"
        "    __table_args__ = (\n"
        f"        Index(\"ix_{table_name}_tenant_created\", \"tenant_id\", \"created_at\"),\n"
        "    )\n"
    )

    # Verify placement: AST-parse the candidate result and confirm
    # __table_args__ lands inside the target class node.
    candidate = src.rstrip("\n") + "\n" + index_block
    _verify_table_args_in_class(candidate, model_name)

    model_file.write_text(candidate)


def _verify_table_args_in_class(src: str, model_name: str) -> None:
    """Assert that ``__table_args__`` is an attribute of *model_name*, not module-scope.

    Parses *src* and walks the AST.  Raises ``RuntimeError`` if the attribute
    is missing from the class body or is found at module level.

    Args:
        src: Python source code to check.
        model_name: PascalCase class name that must own ``__table_args__``.

    Raises:
        RuntimeError: If ``__table_args__`` is at module scope or absent from
            the class body.
    """
    tree = ast.parse(src)
    # Check it is NOT at module scope
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__table_args__":
                    raise RuntimeError(
                        f"__table_args__ was emitted at MODULE scope in {model_name} model "
                        f"— index would never be registered.  This is a tool bug."
                    )
    # Check it IS inside the target class
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == model_name:
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id == "__table_args__":
                            return  # found — all good
    raise RuntimeError(
        f"__table_args__ not found inside class {model_name} after patching — "
        f"the composite tenant index was not registered."
    )


def _patch_crud(crud_file: Path, model_name: str) -> None:
    """Patch CRUD create() to stamp tenant_id from context.

    Args:
        crud_file: Path to ``app/crud/{name}.py``.
        model_name: PascalCase model name.
    """
    src = crud_file.read_text()
    if "require_current_tenant" in src:
        return

    header = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Tenant-scoped create helper — added by add_multi_tenancy tool
        # ---------------------------------------------------------------------------
        import uuid as _mt_uuid
        from sqlalchemy.ext.asyncio import AsyncSession as _MTSession

        from app.core.tenant_context import require_current_tenant as _require_tenant
        from app.models.{lower} import {model} as _{model}


        async def create_tenant_scoped(
            session: _MTSession,
            *,
            obj_in: dict,
        ) -> "{model}":
            \"\"\"Create a new {model} row stamped with the current request's tenant.

            Args:
                session: Async SQLAlchemy session.
                obj_in: Field dict for the new row (must NOT include tenant_id).

            Returns:
                The newly created ORM instance.

            Raises:
                RuntimeError: If no tenant is in context.
            \"\"\"
            tenant_id = _require_tenant()
            obj = _{model}(**obj_in, tenant_id=tenant_id)
            session.add(obj)
            await session.flush()
            await session.refresh(obj)
            return obj
        """).replace("{lower}", model_name.lower()).replace("{model}", model_name)

    crud_file.write_text(src + header)


def _write_tenant_crud(dest: Path) -> None:
    """Write ``app/crud/tenant.py`` with tenant CRUD helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"CRUD helpers for the Tenant model.\"\"\"

        from __future__ import annotations

        import uuid

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.tenant import Tenant
        from app.schemas.tenant import TenantCreate, TenantUpdate


        async def get_by_slug(session: AsyncSession, *, slug: str) -> Tenant | None:
            \"\"\"Fetch a Tenant by its unique slug.

            Args:
                session: Async SQLAlchemy session.
                slug: URL-safe tenant slug.

            Returns:
                Tenant ORM instance or None.
            \"\"\"
            stmt = select(Tenant).where(Tenant.slug == slug)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def get(session: AsyncSession, *, tenant_id: uuid.UUID) -> Tenant | None:
            \"\"\"Fetch a Tenant by its UUID primary key.

            Args:
                session: Async SQLAlchemy session.
                tenant_id: Tenant UUID.

            Returns:
                Tenant ORM instance or None.
            \"\"\"
            stmt = select(Tenant).where(Tenant.id == tenant_id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def create(session: AsyncSession, *, tenant_in: TenantCreate) -> Tenant:
            \"\"\"Create a new Tenant row.

            Args:
                session: Async SQLAlchemy session.
                tenant_in: Validated create schema.

            Returns:
                Newly created Tenant ORM instance.
            \"\"\"
            tenant = Tenant(**tenant_in.model_dump())
            session.add(tenant)
            await session.flush()
            await session.refresh(tenant)
            return tenant


        async def update(
            session: AsyncSession, *, tenant: Tenant, tenant_in: TenantUpdate
        ) -> Tenant:
            \"\"\"Update a Tenant row.

            Args:
                session: Async SQLAlchemy session.
                tenant: Existing Tenant ORM instance.
                tenant_in: Validated update schema (only set fields applied).

            Returns:
                Updated Tenant ORM instance.
            \"\"\"
            update_data = tenant_in.model_dump(exclude_unset=True)
            for field, value in update_data.items():
                setattr(tenant, field, value)
            await session.flush()
            await session.refresh(tenant)
            return tenant


        async def list_tenants(
            session: AsyncSession, *, skip: int = 0, limit: int = 20
        ) -> list[Tenant]:
            \"\"\"Return paginated list of all tenants.

            Args:
                session: Async SQLAlchemy session.
                skip: Pagination offset.
                limit: Page size.

            Returns:
                List of Tenant ORM instances.
            \"\"\"
            stmt = (
                select(Tenant)
                .execution_options(skip_tenant_filter=True)
                .offset(skip)
                .limit(limit)
                .order_by(Tenant.created_at)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())
        """)
    dest.write_text(content)


def _write_tenant_schemas(dest: Path) -> None:
    """Write ``app/schemas/tenant.py`` with Tenant Pydantic schemas.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for the Tenant model.

        Note: tenant_id is intentionally NOT exposed in TenantPublic so that
        multi-tenant details are never leaked in API responses.
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class TenantBase(BaseModel):
            \"\"\"Shared fields for Tenant create/update.

            Attributes:
                slug: URL-safe unique identifier for the tenant.
                name: Human-readable display name.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            slug: str = Field(..., min_length=1, max_length=63)
            name: str = Field(..., min_length=1, max_length=255)


        class TenantCreate(TenantBase):
            \"\"\"Input schema for creating a new Tenant.\"\"\"


        class TenantUpdate(BaseModel):
            \"\"\"Input schema for partially updating a Tenant.

            Attributes:
                name: New display name (optional).
                status: New status — one of 'active', 'suspended', 'archived' (optional).
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            name: str | None = Field(default=None, min_length=1, max_length=255)
            status: str | None = Field(default=None)


        class TenantPublic(TenantBase):
            \"\"\"Output schema for Tenant API responses.

            Attributes:
                id: Tenant UUID primary key.
                status: Current lifecycle status.
                created_at: UTC creation timestamp.
            \"\"\"

            id: uuid.UUID
            status: str
            created_at: datetime
        """)
    dest.write_text(content)


def _write_tenant_routes(dest: Path) -> None:
    """Write ``app/api/routes/tenant.py`` with admin CRUD endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Admin-only CRUD endpoints for Tenant management.\"\"\"

        from __future__ import annotations

        from fastapi import APIRouter, HTTPException, Query, status

        from app.api.deps import CurrentSuperuser, SessionDep
        from app.crud import tenant as crud_tenant
        from app.schemas.tenant import TenantCreate, TenantPublic, TenantUpdate

        router = APIRouter(prefix="/tenants", tags=["tenants"])


        @router.post("/", response_model=TenantPublic, status_code=status.HTTP_201_CREATED)
        async def create_tenant(
            tenant_in: TenantCreate,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> TenantPublic:
            \"\"\"Create a new tenant. Superuser only.

            Args:
                tenant_in: Validated tenant create payload.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 409 if slug already exists.
            \"\"\"
            existing = await crud_tenant.get_by_slug(session, slug=tenant_in.slug)
            if existing:
                raise HTTPException(status_code=409, detail="Tenant slug already exists")
            tenant = await crud_tenant.create(session, tenant_in=tenant_in)
            return TenantPublic.model_validate(tenant)


        @router.get("/", response_model=list[TenantPublic])
        async def list_tenants(
            session: SessionDep,
            current_user: CurrentSuperuser,
            skip: int = Query(default=0, ge=0),
            limit: int = Query(default=20, ge=1, le=100),
        ) -> list[TenantPublic]:
            \"\"\"List all tenants. Superuser only.

            Args:
                session: Injected async DB session.
                current_user: Must be a superuser.
                skip: Pagination offset.
                limit: Page size (1-100).
            \"\"\"
            tenants = await crud_tenant.list_tenants(session, skip=skip, limit=limit)
            return [TenantPublic.model_validate(t) for t in tenants]


        @router.get("/{slug}", response_model=TenantPublic)
        async def get_tenant(
            slug: str,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> TenantPublic:
            \"\"\"Fetch a tenant by slug. Superuser only.

            Args:
                slug: URL-safe tenant slug.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if tenant not found.
            \"\"\"
            tenant = await crud_tenant.get_by_slug(session, slug=slug)
            if tenant is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            return TenantPublic.model_validate(tenant)


        @router.patch("/{slug}", response_model=TenantPublic)
        async def update_tenant(
            slug: str,
            tenant_in: TenantUpdate,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> TenantPublic:
            \"\"\"Update a tenant by slug. Superuser only.

            Args:
                slug: URL-safe tenant slug.
                tenant_in: Validated partial update payload.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if tenant not found.
            \"\"\"
            tenant = await crud_tenant.get_by_slug(session, slug=slug)
            if tenant is None:
                raise HTTPException(status_code=404, detail="Tenant not found")
            tenant = await crud_tenant.update(session, tenant=tenant, tenant_in=tenant_in)
            return TenantPublic.model_validate(tenant)
        """)
    dest.write_text(content)


def _patch_main(main_file: Path) -> None:
    """Register TenantMiddleware and tenant_filter import in main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "TenantMiddleware" in src and "tenant_filter" in src:
        return

    # Add side-effect import for tenant filter
    if "tenant_filter" not in src:
        marker = "from app.core.logging import configure_logging"
        filter_import = "\nimport app.core.tenant_filter  # noqa: F401  — activates global filter"
        if marker in src:
            src = src.replace(marker, marker + filter_import)
        else:
            src = "import app.core.tenant_filter  # noqa: F401\n" + src

    # Register TenantMiddleware after register_middleware call
    if "TenantMiddleware" not in src:
        middleware_import = (
            "\nfrom app.api.middleware.tenant import TenantMiddleware"
        )
        register_marker = "register_middleware(app, settings)"
        if register_marker in src:
            src = src.replace(
                register_marker,
                middleware_import.lstrip("\n")
                + "\n"
                + register_marker
                + "\napp.add_middleware(TenantMiddleware, resolver=\"header\")",
            )
        else:
            src = src + "\nfrom app.api.middleware.tenant import TenantMiddleware\n"
            src = src + "\napp.add_middleware(TenantMiddleware, resolver=\"header\")\n"

    main_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the tenant router in ``app/routes/__init__.py``.

    Appends an import and ``api_router.include_router(tenant_router)`` call
    idempotently.  Without this the tenant CRUD endpoints (POST/GET/PATCH
    ``/tenants``) are never reachable even though the route file exists.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    src = routes_init.read_text()
    if "tenant_router" in src:
        return
    addition = (
        "\n"
        "# --- Tenant admin routes — added by add_multi_tenancy tool ---\n"
        "from app.api.routes.tenant import router as tenant_router  # noqa: E402\n"
        "api_router.include_router(tenant_router)\n"
    )
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def _write_migration(versions_dir: Path, model_names: list[str]) -> Path:
    """Generate an Alembic migration for multi-tenancy.

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_names: PascalCase model names to add tenant_id to.

    Returns:
        Path of the created migration file.
    """
    tables = [m.lower() + "s" for m in model_names]
    rev_id = "0008_add_multi_tenancy"
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    # Build per-table backfill + constraint SQL
    backfill_lines = []
    for table in tables:
        backfill_lines.append(
            "    op.execute(\n"
            "        \"UPDATE {t} SET tenant_id = "
            "(SELECT id FROM tenants WHERE slug='default') "
            "WHERE tenant_id IS NULL;\"\n"
            "    )".format(t=table)
        )
    backfill_block = "\n\n".join(backfill_lines)

    alter_lines = []
    for table in tables:
        alter_lines.append(
            "    op.alter_column(\"{t}\", \"tenant_id\", nullable=False)\n"
            "    op.create_foreign_key(\n"
            "        \"fk_{t}_tenant\", \"{t}\", \"tenants\",\n"
            "        [\"tenant_id\"], [\"id\"], ondelete=\"RESTRICT\"\n"
            "    )\n"
            "    op.create_index(\"ix_{t}_tenant_created\", \"{t}\","
            " [\"tenant_id\", \"created_at\"])".format(t=table)
        )
    alter_block = "\n\n".join(alter_lines)

    add_col_lines = []
    for table in tables:
        add_col_lines.append(
            "    op.add_column(\n"
            "        \"{t}\",\n"
            "        sa.Column(\"tenant_id\", sa.Uuid(), nullable=True),\n"
            "    )".format(t=table)
        )
    add_col_block = "\n\n".join(add_col_lines)

    drop_lines = []
    for table in reversed(tables):
        drop_lines.append(
            "    op.drop_index(\"ix_{t}_tenant_created\", table_name=\"{t}\")\n"
            "    op.drop_constraint(\"fk_{t}_tenant\", \"{t}\","
            " type_=\"foreignkey\")\n"
            "    op.drop_column(\"{t}\", \"tenant_id\")".format(t=table)
        )
    drop_block = "\n\n".join(drop_lines)

    content = textwrap.dedent("""\
        \"\"\"Add multi-tenancy: tenants table + tenant_id columns.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_multi_tenancy tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create tenants table, backfill existing rows, promote NOT NULL.\"\"\"
            # 1. Create tenants table
            op.create_table(
                "tenants",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("slug", sa.String(63), nullable=False, unique=True),
                sa.Column("name", sa.String(255), nullable=False),
                sa.Column(
                    "status", sa.String(16), server_default="active", nullable=False
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "status IN ('active','suspended','archived')",
                    name="ck_tenants_status",
                ),
                sa.CheckConstraint(
                    "length(slug) >= 1 AND length(slug) <= 63",
                    name="ck_tenants_slug_format",
                ),
            )

            # 2. Insert default tenant for backfill
            op.execute(
                "INSERT INTO tenants (id, slug, name) VALUES "
                "(gen_random_uuid(), 'default', 'Default Tenant')"
            )

            # 3. Add tenant_id column to each business model (nullable initially)
        {add_col_block}

            # 4. Backfill: assign existing rows to default tenant
        {backfill_block}

            # 5. Promote to NOT NULL + FK + composite index
        {alter_block}


        def downgrade() -> None:
            \"\"\"Drop tenant_id columns and tenants table.\"\"\"
        {drop_block}

            op.drop_table("tenants")
        """).format(
        rev_id=rev_id,
        down_rev=down_rev,
        add_col_block=add_col_block,
        backfill_block=backfill_block,
        alter_block=alter_block,
        drop_block=drop_block,
    )

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
