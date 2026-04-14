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
        return ToolResult(status="error", error=err)

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

    files_created: list[str] = []
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

    # --- Step 11: Patch main.py to register middleware + filter import ---
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

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
            "Global ORM filter registered via do_orm_execute — every SELECT auto-scoped.",
            "TenantMiddleware registered in main.py; resolves tenant from X-Tenant-ID header.",
            "Tenant schemas (Public/Create/Update) exclude tenant_id from responses.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Restart the application so tenant_filter side-effect import runs.",
            "Seed the default tenant: POST /tenants/ {slug: 'default', name: 'Default Tenant'}",
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
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    This avoids patching infrastructure files like ``mfa.py``, ``api_key.py``,
    or ``feature_flag.py`` (route is ``feature_flags.py``, not ``feature_flag.py``).

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of discovered model names (e.g. ``["Item"]``).
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
        # Derive PascalCase class name: item -> Item, order_item -> OrderItem
        pascal = "".join(w.capitalize() for w in stem.split("_"))
        # Verify the file contains a class with exactly this name inheriting Base
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
        if pascal in base_subclasses:
            names.append(pascal)
    return names


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

        Example::

            # main.py — side-effect import (no symbol needed)
            import app.core.tenant_filter  # noqa: F401
        \"\"\"

        from sqlalchemy import event
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
        \"\"\"Middleware that resolves and validates the tenant for each request.

        Extracts the tenant slug from the X-Tenant-ID header, looks up the
        Tenant record, and sets the per-request tenant context.  Requests
        to TENANT_FREE_PATHS bypass tenant resolution.
        \"\"\"

        from __future__ import annotations

        from fastapi import Request
        from sqlalchemy import select
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.responses import JSONResponse

        from app.core.session import async_session as async_session_maker
        from app.core.tenant_context import set_current_tenant
        from app.models.tenant import Tenant

        TENANT_FREE_PATHS = {
            "/api/v1/login/access-token",
            "/api/v1/users/signup",
            "/api/v1/auth/register",
            "/health",
            "/healthz",
            "/readyz",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/openapi.json",
        }


        class TenantMiddleware(BaseHTTPMiddleware):
            \"\"\"Resolve tenant from request; set in ContextVar before view runs.

            Args:
                app: ASGI application.
                resolver: How to extract the tenant slug.
                    'header' reads X-Tenant-ID (default).
                    'subdomain' reads the first subdomain component from Host.
                    'jwt' reads request.state.tenant_slug (set by auth dep).
            \"\"\"

            def __init__(self, app, resolver: str = "header") -> None:
                super().__init__(app)
                self.resolver = resolver

            async def dispatch(self, request: Request, call_next):
                \"\"\"Resolve tenant and set context before forwarding request.

                Args:
                    request: Incoming HTTP request.
                    call_next: Next ASGI handler.

                Returns:
                    HTTP response, or a 400/403/404 JSON error if tenant is invalid.
                \"\"\"
                if request.url.path in TENANT_FREE_PATHS:
                    set_current_tenant(None)
                    return await call_next(request)

                slug = self._extract_slug(request)
                if not slug:
                    return JSONResponse(
                        {"detail": "Tenant not specified"}, status_code=400
                    )

                async with async_session_maker() as session:
                    stmt = select(Tenant).where(Tenant.slug == slug)
                    tenant = (await session.execute(stmt)).scalar_one_or_none()

                if tenant is None:
                    return JSONResponse({"detail": "Unknown tenant"}, status_code=404)
                if tenant.status != "active":
                    return JSONResponse({"detail": "Tenant is not active"}, status_code=403)

                set_current_tenant(tenant.id)
                try:
                    return await call_next(request)
                finally:
                    set_current_tenant(None)

            def _extract_slug(self, request: Request) -> str | None:
                \"\"\"Extract tenant slug from request using the configured resolver.

                Args:
                    request: Incoming HTTP request.

                Returns:
                    Tenant slug string, or None if not found.
                \"\"\"
                if self.resolver == "header":
                    return request.headers.get("X-Tenant-ID")
                if self.resolver == "subdomain":
                    host = request.headers.get("host", "")
                    return host.split(".")[0] if "." in host else None
                if self.resolver == "jwt":
                    return getattr(request.state, "tenant_slug", None)
                return None
        """)
    dest.write_text(content)


def _patch_model(model_file: Path, model_name: str) -> None:
    """Inject TenantScopedMixin into a model class and add composite index.

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

    # Append composite index
    index_block = textwrap.dedent("""\

            __table_args__ = (
                Index("ix_{table}_tenant_created", "tenant_id", "created_at"),
            )
        """).replace("{table}", table_name)

    src = src.rstrip("\n") + "\n" + index_block
    model_file.write_text(src)


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
