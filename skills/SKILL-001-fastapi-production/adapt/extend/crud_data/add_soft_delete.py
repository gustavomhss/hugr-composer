"""TOOL-001: add_soft_delete — add soft-delete to a FastAPI/SQLAlchemy project.

Adds three audit columns (``is_deleted``, ``deleted_at``, ``deleted_by``) to
every target model via a shared ``SoftDeleteMixin``, wires a global
``do_orm_execute`` filter so all default SELECTs exclude deleted rows, extends
CRUD modules with ``soft_delete`` / ``restore`` / ``hard_delete`` helpers, adds
the matching route handlers, generates an Alembic migration, and registers the
filter import in ``main.py``.

The tool is idempotent: a second run on an already-patched project detects the
``SoftDeleteMixin`` fingerprint and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_soft_delete import add_soft_delete

    result = add_soft_delete(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/models/mixins.py", ...]
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
    "name": "fastapi_add_soft_delete",
    "description": "Add soft delete to all models in the project.",
    "tags": ["extend", "crud_data"],
    "entry": "add_soft_delete",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_soft_delete(inp: ToolInput) -> ToolResult:
    """Add soft-delete capability to a FastAPI project.

    Reads the project at ``inp.project_dir``, detects which models exist,
    and writes / patches all necessary files.  Returns a ``ToolResult``
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

    # --- Prerequisite check -----------------------------------------------
    from adapt.contracts.prerequisites import check_prerequisites, Prereq

    prereq_errors = check_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.MODELS_INIT,
        Prereq.CONFIG_SETTINGS,
        Prereq.ALEMBIC_VERSIONS,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=[
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='minimal', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"

    # --- Pre-flight: is soft-delete already enabled? ----------------------
    mixins_file = app_dir / "models" / "mixins.py"
    if mixins_file.exists() and "SoftDeleteMixin" in mixins_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["SoftDeleteMixin already present — soft-delete is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Discover target models -------------------------------------------
    model_pairs = _discover_models(app_dir)
    if not model_pairs:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )
    model_names = [pascal for _stem, pascal in model_pairs]

    files_created: list[str] = []
    files_modified: list[str] = []

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add SoftDeleteMixin for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Step 1: SoftDeleteMixin ------------------------------------------
    _write_mixin(mixins_file)
    files_created.append(str(mixins_file))

    # --- Step 2: Patch each model to inherit SoftDeleteMixin --------------
    for stem, model_name in model_pairs:
        model_file = app_dir / "models" / f"{stem}.py"
        if model_file.exists():
            _patch_model(model_file, model_name)
            files_modified.append(str(model_file))

    # --- Step 3: Global query filter -------------------------------------
    filter_file = app_dir / "core" / "soft_delete_filter.py"
    _write_filter(filter_file)
    files_created.append(str(filter_file))

    # --- Step 4: Patch main.py to import the filter ----------------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 5: Extend CRUD modules with helpers ------------------------
    for stem, model_name in model_pairs:
        crud_file = app_dir / "crud" / f"{stem}.py"
        if crud_file.exists():
            _patch_crud(crud_file, model_name)
            files_modified.append(str(crud_file))

    # --- Step 6: Patch route files with soft-delete endpoints ------------
    for stem, model_name in model_pairs:
        route_file = app_dir / "api" / "routes" / f"{stem}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

    # --- Step 7: Patch schemas with ItemDeletedPublic --------------------
    for stem, model_name in model_pairs:
        schema_file = app_dir / "schemas" / f"{stem}.py"
        if schema_file.exists():
            _patch_schema(schema_file, model_name)
            files_modified.append(str(schema_file))

    # --- Step 8: Generate Alembic migration ------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        for _stem, model_name in model_pairs:
            migration_file = _write_migration(versions_dir, model_name)
            files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Soft-delete enabled for: {', '.join(model_names)}",
            "Global query filter registered via do_orm_execute session event.",
            "ItemPublic schema does NOT expose is_deleted/deleted_at/deleted_by.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Restart the application so the soft_delete_filter side-effect import runs.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs from ``app/models/``, excluding system files.

    Only includes models where:
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    This avoids patching infrastructure models added by other tools (e.g.
    ``feature_flag.py`` → ``feature_flags.py`` route, ``mfa.py`` → no matching
    ``Mfa(Base)`` class, ``tenant.py`` → ``tenant.py`` route but already skipped).

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of ``(snake_stem, PascalName)`` tuples.
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    pairs: list[tuple[str, str]] = []
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if stem not in available_routes:
            continue
        pascal = "".join(w.capitalize() for w in stem.split("_"))
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
            pairs.append((stem, pascal))
    return pairs


def _write_mixin(dest: Path) -> None:
    """Write or extend ``app/models/mixins.py`` with ``SoftDeleteMixin``.

    If the file already exists (e.g. ``TenantScopedMixin`` was added by
    ``add_multi_tenancy``), the new class is APPENDed so existing mixins are
    preserved.

    Args:
        dest: Absolute path for the file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Standalone block that works whether we write fresh or append.
    # Imports are repeated deliberately so the class is self-contained when appended.
    mixin_block = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # SoftDeleteMixin — added by add_soft_delete tool
        # ---------------------------------------------------------------------------
        import uuid as _sd_uuid
        from datetime import datetime as _sd_datetime
        from sqlalchemy import Boolean as _sd_Boolean, DateTime as _sd_DateTime
        from sqlalchemy import ForeignKey as _sd_ForeignKey, Uuid as _sd_Uuid
        from sqlalchemy.orm import declared_attr as _sd_declared_attr
        from sqlalchemy.orm import Mapped as _sd_Mapped, mapped_column as _sd_mapped_column


        class SoftDeleteMixin:
            \"\"\"Mix-in adding is_deleted, deleted_at, and deleted_by columns.

            Inherit *before* Base::

                class Item(SoftDeleteMixin, Base): ...

            Attributes:
                is_deleted: Boolean flag.  DB server_default='false' means
                    ALTER TABLE is metadata-only on PG 11+ (no table rewrite).
                deleted_at: UTC timestamp of deletion, nullable.
                deleted_by: FK to users.id, nullable, SET NULL on user delete.
            \"\"\"

            @_sd_declared_attr
            def is_deleted(cls) -> _sd_Mapped[bool]:
                return _sd_mapped_column(
                    _sd_Boolean, default=False, nullable=False, server_default="false"
                )

            @_sd_declared_attr
            def deleted_at(cls) -> _sd_Mapped[_sd_datetime | None]:
                return _sd_mapped_column(_sd_DateTime(timezone=True), nullable=True)

            @_sd_declared_attr
            def deleted_by(cls) -> _sd_Mapped[_sd_uuid.UUID | None]:
                return _sd_mapped_column(
                    _sd_Uuid,
                    _sd_ForeignKey("users.id", ondelete="SET NULL"),
                    nullable=True,
                )
        """)

    if dest.exists():
        existing = dest.read_text()
        dest.write_text(existing.rstrip("\n") + "\n" + mixin_block)
    else:
        header = textwrap.dedent("""\
            \"\"\"Reusable SQLAlchemy mixins for soft-delete and other cross-cutting concerns.\"\"\"

            from __future__ import annotations
            """)
        dest.write_text(header + mixin_block)


def _patch_model(model_file: Path, model_name: str) -> None:
    """Inject SoftDeleteMixin into a model class and add a composite index.

    Args:
        model_file: Path to the model ``.py`` file.
        model_name: PascalCase class name (e.g. ``"Item"``).
    """
    src = model_file.read_text()

    # Already patched?
    if "SoftDeleteMixin" in src:
        return

    table_name = model_name.lower() + "s"

    # Add import for SoftDeleteMixin
    mixin_import = "from app.models.mixins import SoftDeleteMixin\n"
    if mixin_import not in src:
        src = src.replace(
            "from app.models.base import Base",
            "from app.models.base import Base\nfrom app.models.mixins import SoftDeleteMixin",
        )

    # Add Index to sqlalchemy imports if missing — handle both single-line and
    # multi-line forms (e.g., "from sqlalchemy import (\n    Column,\n)")
    import re as _re
    if "Index" not in src:
        _multi = _re.search(r"(from sqlalchemy import\s*\()", src)
        if _multi:
            src = src[: _multi.end()] + "\n    Index," + src[_multi.end():]
        elif "from sqlalchemy import" in src:
            src = src.replace("from sqlalchemy import", "from sqlalchemy import Index,", 1)

    # Patch class declaration: class Foo(Base) -> class Foo(SoftDeleteMixin, Base)
    src = src.replace(
        f"class {model_name}(Base):",
        f"class {model_name}(SoftDeleteMixin, Base):",
    )

    # Append composite index __table_args__ before end of class
    # Append after the last mapped_column line.
    index_block = textwrap.dedent("""\

            __table_args__ = (
                # Composite index: hot-path filter is_deleted=False ORDER BY created_at
                Index("ix_{table}_active", "is_deleted", "created_at"),
            )
        """).replace("{table}", table_name)

    # Insert just before end of file (handles trailing newline)
    src = src.rstrip("\n") + "\n" + index_block

    model_file.write_text(src)


def _write_filter(dest: Path) -> None:
    """Write ``app/core/soft_delete_filter.py`` with the session event listener.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Global soft-delete query filter via SQLAlchemy session event.

        Import this module once at application startup (main.py) to activate
        the filter.  Every SELECT against a SoftDeleteMixin model will
        automatically receive a ``WHERE is_deleted = false`` predicate unless
        the execution option ``include_deleted=True`` is set.

        Example::

            # main.py — side-effect import (no symbol needed)
            import app.core.soft_delete_filter  # noqa: F401
        \"\"\"

        from sqlalchemy import event
        from sqlalchemy.orm import Session, with_loader_criteria

        from app.models.mixins import SoftDeleteMixin


        @event.listens_for(Session, "do_orm_execute")
        def _enforce_soft_delete_filter(execute_state) -> None:
            \"\"\"Inject WHERE is_deleted = false for every default SELECT.

            Args:
                execute_state: SQLAlchemy ORM execute state object.

            Skip by passing execution option ``include_deleted=True``::

                stmt = select(Item).execution_options(include_deleted=True)
            \"\"\"
            if not execute_state.is_select:
                return
            if execute_state.execution_options.get("include_deleted"):
                return

            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    SoftDeleteMixin,
                    lambda cls: cls.is_deleted == False,  # noqa: E712
                    include_aliases=True,
                )
            )
        """)
    dest.write_text(content)


def _patch_main(main_file: Path) -> None:
    """Add side-effect import of soft_delete_filter to main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "soft_delete_filter" in src:
        return

    # Insert after configure_logging import block
    marker = "from app.core.logging import configure_logging"
    filter_import = "\nimport app.core.soft_delete_filter  # noqa: F401  — activates global filter"
    if marker in src:
        src = src.replace(marker, marker + filter_import)
    else:
        # Fallback: prepend after first import block
        src = "import app.core.soft_delete_filter  # noqa: F401\n" + src

    main_file.write_text(src)


def _patch_crud(crud_file: Path, model_name: str) -> None:
    """Append soft_delete, restore, hard_delete, list_deleted to a CRUD module.

    Args:
        crud_file: Path to ``app/crud/{name}.py``.
        model_name: PascalCase model name.
    """
    src = crud_file.read_text()
    if "soft_delete" in src:
        return

    lower = model_name.lower()

    # Deduplicate imports that may already exist from a previously-run tool.
    crud_import_lines = [
        "import uuid as _uuid",
        "from datetime import datetime as _dt, timezone as _tz",
        "from sqlalchemy import func as _func, select as _select",
        "from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession",
    ]
    new_crud_imports = "\n".join(
        line for line in crud_import_lines if line.strip() not in src
    )

    additions = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Soft-delete helpers — added by add_soft_delete tool
        # ---------------------------------------------------------------------------
        {new_crud_imports}


        async def soft_delete(
            session: _AsyncSession,
            item_id: _uuid.UUID,
            *,
            deleted_by: _uuid.UUID | None = None,
        ) -> "{model_name} | None":
            \"\"\"Soft-delete: set is_deleted=True, deleted_at=now(UTC).

            Args:
                session: Async SQLAlchemy session.
                item_id: Primary key of the row to soft-delete.
                deleted_by: UUID of the acting user (for audit trail).

            Returns:
                The updated ORM instance, or ``None`` if not found.
            \"\"\"
            stmt = _select({model_name}).where(
                {model_name}.id == item_id, {model_name}.is_deleted == False  # noqa: E712
            )
            obj = (await session.execute(stmt)).scalar_one_or_none()
            if obj is None:
                return None
            obj.is_deleted = True
            obj.deleted_at = _dt.now(_tz.utc)
            if deleted_by is not None:
                obj.deleted_by = deleted_by
            await session.flush()
            return obj


        async def restore(
            session: _AsyncSession, item_id: _uuid.UUID
        ) -> "{model_name} | None":
            \"\"\"Restore a soft-deleted row. Atomically clears all three deletion columns.

            Args:
                session: Async SQLAlchemy session.
                item_id: Primary key of the row to restore.

            Returns:
                The restored ORM instance, or ``None`` if not found in deleted records.
            \"\"\"
            stmt = (
                _select({model_name})
                .where({model_name}.id == item_id, {model_name}.is_deleted == True)  # noqa: E712
                .execution_options(include_deleted=True)
            )
            obj = (await session.execute(stmt)).scalar_one_or_none()
            if obj is None:
                return None
            obj.is_deleted = False
            obj.deleted_at = None
            obj.deleted_by = None
            await session.flush()
            return obj


        async def hard_delete(
            session: _AsyncSession, item_id: _uuid.UUID
        ) -> "{model_name} | None":
            \"\"\"Permanently remove a row. Superuser-only path.

            Args:
                session: Async SQLAlchemy session.
                item_id: Primary key of the row to destroy.

            Returns:
                The deleted ORM instance, or ``None`` if not found.
            \"\"\"
            stmt = (
                _select({model_name})
                .where({model_name}.id == item_id)
                .execution_options(include_deleted=True)
            )
            obj = (await session.execute(stmt)).scalar_one_or_none()
            if obj is None:
                return None
            await session.delete(obj)
            await session.flush()
            return obj


        async def list_deleted(
            session: _AsyncSession, *, skip: int = 0, limit: int = 20
        ) -> dict:
            \"\"\"Return paginated soft-deleted rows. Admin use only.

            Args:
                session: Async SQLAlchemy session.
                skip: Offset for pagination.
                limit: Page size (max 100).

            Returns:
                Dict with ``data`` list and ``count`` total.
            \"\"\"
            stmt = (
                _select({model_name})
                .where({model_name}.is_deleted == True)  # noqa: E712
                .execution_options(include_deleted=True)
                .order_by({model_name}.deleted_at.desc())
                .offset(skip)
                .limit(limit)
            )
            count_stmt = _select(_func.count()).select_from(
                _select({model_name})
                .where({model_name}.is_deleted == True)  # noqa: E712
                .execution_options(include_deleted=True)
                .subquery()
            )
            total = (await session.execute(count_stmt)).scalar_one()
            result = await session.execute(stmt)
            return {"data": list(result.scalars().all()), "count": total}
        """).replace("{new_crud_imports}", new_crud_imports).replace("{model_name}", model_name)

    crud_file.write_text(src + additions)


def _patch_routes(route_file: Path, model_name: str) -> None:
    """Append soft-delete, restore, hard-delete, list-deleted endpoints.

    Args:
        route_file: Path to ``app/api/routes/{name}.py``.
        model_name: PascalCase model name.
    """
    src = route_file.read_text()
    if "soft_delete" in src or "/restore" in src:
        return

    lower = model_name.lower()

    # Build a header with only the imports that are not already present.
    # Using flat (single-line) imports avoids duplicate "from app.crud.X import ("
    # opening lines when multiple tools patch the same route file.
    import_header_lines = [
        f"from app.crud.{lower} import soft_delete as _crud_soft_delete",
        f"from app.crud.{lower} import restore as _crud_restore",
        f"from app.crud.{lower} import hard_delete as _crud_hard_delete",
        f"from app.crud.{lower} import list_deleted as _crud_list_deleted",
        "import uuid as _route_uuid",
        "from fastapi import HTTPException",
        "from fastapi import Query as _Query",
    ]
    new_imports = "\n".join(
        line for line in import_header_lines if line.strip() not in src
    )

    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Soft-delete endpoints — added by add_soft_delete tool
        # ---------------------------------------------------------------------------
        {import_header}


        @router.delete("/{{item_id}}", response_model={PublicSchema})
        async def soft_delete_{lower}(
            item_id: _route_uuid.UUID,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> {PublicSchema}:
            \"\"\"Soft-delete a {model_name}. Sets is_deleted=True; row remains in DB.

            Args:
                item_id: UUID of the {model_name} to soft-delete.
                session: Injected async DB session.
                current_user: Authenticated user (used for deleted_by).

            Raises:
                HTTPException: 404 if not found.
            \"\"\"
            item = await _crud_soft_delete(session, item_id, deleted_by=current_user.id)
            if item is None:
                raise HTTPException(status_code=404, detail="{model_name} not found")
            return item


        @router.post("/{{item_id}}/restore", response_model={PublicSchema})
        async def restore_{lower}(
            item_id: _route_uuid.UUID,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> {PublicSchema}:
            \"\"\"Restore a soft-deleted {model_name}. Superuser only.

            Args:
                item_id: UUID of the {model_name} to restore.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if not found in deleted records.
            \"\"\"
            item = await _crud_restore(session, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="{model_name} not found in deleted records")
            return item


        @router.delete("/{{item_id}}/permanent", response_model=Message)
        async def hard_delete_{lower}(
            item_id: _route_uuid.UUID,
            session: SessionDep,
            current_user: CurrentSuperuser,
        ) -> Message:
            \"\"\"Permanently destroy a {model_name}. Superuser only. Irreversible.

            Args:
                item_id: UUID of the {model_name} to destroy.
                session: Injected async DB session.
                current_user: Must be a superuser.

            Raises:
                HTTPException: 404 if not found.
            \"\"\"
            item = await _crud_hard_delete(session, item_id)
            if item is None:
                raise HTTPException(status_code=404, detail="{model_name} not found")
            return Message(message=f"{model_name} {{item_id}} permanently deleted")


        @router.get("/deleted/", response_model={DeletedListSchema})
        async def list_deleted_{lower}s(
            session: SessionDep,
            current_user: CurrentSuperuser,
            skip: int = _Query(default=0, ge=0),
            limit: int = _Query(default=20, ge=1, le=100),
        ) -> {DeletedListSchema}:
            \"\"\"List all soft-deleted {model_name}s. Superuser only.

            Args:
                session: Injected async DB session.
                current_user: Must be a superuser.
                skip: Pagination offset.
                limit: Page size (1-100).
            \"\"\"
            return {DeletedListSchema}(**await _crud_list_deleted(session, skip=skip, limit=limit))
        """).format(
        lower=lower,
        model_name=model_name,
        PublicSchema=f"{model_name}Public",
        DeletedListSchema=f"{model_name}sDeletedPublic",
        import_header=new_imports,
    )

    # Ensure CurrentSuperuser is imported
    if "CurrentSuperuser" not in src:
        src = src.replace(
            "from app.api.deps import CurrentUser",
            "from app.api.deps import CurrentUser, CurrentSuperuser",
        )
    # Ensure Message is imported
    if "from app.schemas.message import Message" not in src:
        src = src + "\nfrom app.schemas.message import Message\n"
    # Ensure ItemsDeletedPublic schema is imported in the routes file
    deleted_list_schema = f"{model_name}sDeletedPublic"
    if deleted_list_schema not in src:
        src = src + f"\nfrom app.schemas.{lower} import {deleted_list_schema}\n"

    route_file.write_text(src + additions)


def _patch_schema(schema_file: Path, model_name: str) -> None:
    """Append ItemDeletedPublic and ItemsDeletedPublic schemas.

    Args:
        schema_file: Path to ``app/schemas/{name}.py``.
        model_name: PascalCase model name.
    """
    src = schema_file.read_text()
    deleted_class = f"{model_name}DeletedPublic"
    if deleted_class in src:
        return

    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Soft-delete schemas — added by add_soft_delete tool
        # NOTE: {model_name}Public intentionally EXCLUDES is_deleted/deleted_at/deleted_by
        # ---------------------------------------------------------------------------
        import uuid as _schema_uuid
        from datetime import datetime as _schema_datetime


        class {model_name}DeletedPublic({model_name}Public):
            \"\"\"Extended schema for the /deleted/ admin endpoint only.

            Exposes the three deletion columns that {model_name}Public deliberately omits.

            Attributes:
                is_deleted: Always True for records in this schema.
                deleted_at: UTC timestamp when the row was soft-deleted.
                deleted_by: UUID of the user who triggered the deletion, if recorded.
            \"\"\"

            is_deleted: bool
            deleted_at: _schema_datetime
            deleted_by: _schema_uuid.UUID | None = None


        class {model_name}sDeletedPublic(BaseModel):
            \"\"\"Paginated list of soft-deleted {model_name} records.

            Attributes:
                data: Page of soft-deleted records.
                count: Total soft-deleted records (before pagination).
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            data: list[{model_name}DeletedPublic]
            count: int
        """).replace("{model_name}", model_name)

    # Ensure ConfigDict is imported (may already be present)
    if "ConfigDict" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict",
        )

    schema_file.write_text(src + additions)


def _write_migration(versions_dir: Path, model_name: str) -> Path:
    """Generate an Alembic migration adding soft-delete columns.

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_name: PascalCase model name (e.g. ``"Item"``).

    Returns:
        Path of the created migration file.
    """
    table = model_name.lower() + "s"
    rev_id = f"softdel_{table}"
    # Find the true HEAD of the migration chain (not just alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    content = textwrap.dedent("""\
        \"\"\"Add soft-delete columns to {table} table.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_soft_delete tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Add is_deleted, deleted_at, deleted_by columns and composite index.\"\"\"
            # server_default='false' → metadata-only ALTER on PG 11+ (no table rewrite)
            op.add_column(
                "{table}",
                sa.Column(
                    "is_deleted",
                    sa.Boolean(),
                    server_default=sa.false(),
                    nullable=False,
                ),
            )
            op.add_column(
                "{table}",
                sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            )
            op.add_column(
                "{table}",
                sa.Column("deleted_by", sa.Uuid(), nullable=True),
            )
            op.create_foreign_key(
                "fk_{table}_deleted_by_users",
                "{table}",
                "users",
                ["deleted_by"],
                ["id"],
                ondelete="SET NULL",
            )
            # Composite index: hot-path filter WHERE is_deleted=False ORDER BY created_at
            op.create_index("ix_{table}_active", "{table}", ["is_deleted", "created_at"])


        def downgrade() -> None:
            \"\"\"Remove soft-delete columns and associated constraints.\"\"\"
            op.drop_index("ix_{table}_active", table_name="{table}")
            op.drop_constraint("fk_{table}_deleted_by_users", "{table}", type_="foreignkey")
            op.drop_column("{table}", "deleted_by")
            op.drop_column("{table}", "deleted_at")
            op.drop_column("{table}", "is_deleted")
        """).format(table=table, rev_id=rev_id, down_rev=down_rev)

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
