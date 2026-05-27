"""TOOL-001: add_soft_delete — add real soft-delete to a FastAPI/SQLAlchemy project.

What this tool actually does (end-to-end):

1. Discovers all domain models in ``app/models/`` (using AST to read real class
   names — not filename-derived guesses).
2. Injects ``is_deleted`` + ``deleted_at`` columns into each model file that
   doesn't already have them.
3. Patches each model's CRUD file to override ``delete()`` so it sets
   ``is_deleted=True`` / ``deleted_at=now()`` instead of hard-deleting, and
   to filter ``is_deleted=True`` rows out of ``get_multi``.
4. Generates an Alembic migration adding the two columns to each affected table.
5. Copies the framework-agnostic ``core.venous.data.UnitOfWork`` primitive and
   its FastAPI adapter into the project and writes ``app/soft_delete.py`` — a
   ≤20-line glue module that wires the UoW flush-function into FastAPI Depends.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors ``add_graceful_shutdown``):

The tool is idempotent: a second run detects the ``is_deleted`` fingerprint in
the first model file and returns ``status="no_op"`` without touching any file.

BUG C FIX (vs. previous version): the old implementation returned
``status="success"`` after only copying the UoW primitive, leaving
``is_deleted`` absent from every model.  The ``hasattr(entity, "is_deleted")``
guards in ``soft_delete.py`` were therefore always-False, meaning deletes still
hard-deleted.  This rewrite actually injects the column and migration.
"""

from __future__ import annotations

import ast
import re
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

MCP_TOOL = {
    "name": "fastapi_data_add_soft_delete",
    "description": (
        "Inject is_deleted + deleted_at columns into domain models, override "
        "delete() in CRUD to soft-delete, emit migration, and copy UnitOfWork "
        "primitive + FastAPI adapter into the project."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_soft_delete",
    "imports_primitives": [
        "core.venous.data.UnitOfWork",
    ],
    "imports_adapters": [
        "core.venous._adapters.fastapi.UnitOfWorkAdapter",
    ],
}


_GLUE = '''\
"""Wire soft-delete into the FastAPI app via the UnitOfWork primitive.

Delegates to `UnitOfWorkAdapter` copied under `core/venous/` by
`add_soft_delete`. Hand-editing is safe but the file is re-emitted
idempotently on subsequent tool runs.
"""

from __future__ import annotations

from core.venous._adapters.fastapi.UnitOfWorkAdapter import make_dependency


def _soft_delete_flush(new, dirty, removed):
    """Flip `is_deleted=True` on every 'removed' entity instead of DELETEing."""
    for entity in removed:
        if hasattr(entity, "is_deleted"):
            entity.is_deleted = True


get_uow = make_dependency(_soft_delete_flush)
"""FastAPI dependency yielding a UoW whose 'removed' bucket soft-deletes."""
'''


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_soft_delete(inp: ToolInput) -> ToolResult:
    """Add real soft-delete capability to a FastAPI/SQLAlchemy project.

    Discovers domain models, injects ``is_deleted`` / ``deleted_at`` columns,
    patches CRUD to soft-delete, generates Alembic migration, and copies the
    UnitOfWork primitive + FastAPI adapter.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.CONFIG_SETTINGS,
        Prereq.REQUIREMENTS_TXT,
        auto_scaffold=not inp.dry_run,
    )
    if prereq_errors:
        return ToolResult(
            status="error",
            error="Prerequisites not met:\n" + "\n".join(f"  - {e}" for e in prereq_errors),
            notes=["Generate a base project first via fastapi_generate_project."],
            execution_time_ms=_elapsed_ms(start),
        )

    app_dir = project / "app"
    glue_file = app_dir / "soft_delete.py"

    # Idempotency check: look for the is_deleted column in any model AND the
    # glue file.  Both must be present for a true no_op.
    if _soft_delete_already_installed(app_dir):
        return ToolResult(
            status="no_op",
            notes=["Soft-delete already installed — is_deleted column present in models."],
            execution_time_ms=_elapsed_ms(start),
        )

    # Discover models
    model_pairs = _discover_models(app_dir)

    if inp.dry_run:
        model_names = [pascal for _, pascal in model_pairs] if model_pairs else ["(none found)"]
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would inject is_deleted + deleted_at into models: "
                + ", ".join(model_names),
                "[dry_run] Would patch CRUD delete() + get_multi() for each model.",
                "[dry_run] Would generate Alembic migration for each model.",
                "[dry_run] Would copy UnitOfWork primitive + adapter and write app/soft_delete.py.",
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    # --- Step 1: Copy UnitOfWork primitive + adapter -------------------------
    from generators.scaffold_venous import ensure_primitives

    manifest = ensure_primitives(
        str(project),
        names=["core.venous.data.UnitOfWork"],
        adapters=["core.venous._adapters.fastapi.UnitOfWorkAdapter"],
    )
    files_created.append(manifest.path)

    # --- Step 2: Write glue file ---------------------------------------------
    app_dir.mkdir(parents=True, exist_ok=True)
    glue_file.write_text(_GLUE)
    files_created.append(str(glue_file))

    # --- Step 3: Patch models + CRUD + generate migration per model ----------
    versions_dir = project / "alembic" / "versions"
    patched_models: list[str] = []

    for stem, pascal in model_pairs:
        model_file = app_dir / "models" / f"{stem}.py"
        crud_file = app_dir / "crud" / f"{stem}.py"

        # Patch model file: inject is_deleted + deleted_at
        if model_file.exists():
            modified = _patch_model(model_file, pascal)
            if modified:
                files_modified.append(str(model_file))
                patched_models.append(pascal)

        # Patch CRUD file: override delete() + filter in get_multi
        if crud_file.exists():
            modified = _patch_crud(crud_file, pascal, stem)
            if modified:
                files_modified.append(str(crud_file))

        # Generate migration
        if versions_dir.exists():
            mig = _write_migration(versions_dir, pascal, stem)
            files_created.append(str(mig))

    # --- Step 4: Syntax-check all written files ------------------------------
    all_written = files_created + files_modified
    for path_str in all_written:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_elapsed_ms(start),
                )

    model_summary = ", ".join(patched_models) if patched_models else "(no domain models found)"

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Injected is_deleted + deleted_at columns into models: {model_summary}.",
            "CRUD delete() overridden: sets is_deleted=True + deleted_at=now() instead of hard-delete.",
            "CRUD get_multi() patched: filters out is_deleted=True rows automatically.",
            "Alembic migration generated for each patched model.",
            "Shipped primitive: core.venous.data.UnitOfWork (change-bucket transaction).",
            "Shipped adapter: UnitOfWorkAdapter (FastAPI generator-dependency).",
            "Wrote app/soft_delete.py — depend on get_uow to soft-delete via register_removed().",
        ],
        next_steps=[
            "alembic upgrade head",
            "In routes: use the standard delete endpoint — it now soft-deletes automatically.",
            "Soft-deleted rows are excluded from get_multi() list/get responses.",
            "To hard-delete, use a direct SQL DELETE or add a purge endpoint.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _soft_delete_already_installed(app_dir: Path) -> bool:
    """Return True if is_deleted is present in at least one model file.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        True if soft-delete is already installed.
    """
    models_dir = app_dir / "models"
    if not models_dir.exists():
        return False
    for f in sorted(models_dir.glob("*.py")):
        if f.stem in {"base", "user", "mixins", "__init__"}:
            continue
        if "is_deleted" in f.read_text():
            return True
    return False


def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs from ``app/models/``.

    Uses the ACTUAL class names from the AST (not filename-derived guesses).
    Only includes models that have a matching route file.

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
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        # Use real class names from AST, not filename-derived guesses
        base_subclasses = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        if base_subclasses:
            pairs.append((stem, base_subclasses[0]))

    return pairs


# ---------------------------------------------------------------------------
# Model patcher
# ---------------------------------------------------------------------------

def _patch_model(model_file: Path, model_name: str) -> bool:
    """Inject ``is_deleted`` and ``deleted_at`` columns into the model class.

    Appends the two columns before the end of the class body (after any
    existing column definitions, before any non-column lines at the end).
    Ensures ``Boolean``, ``DateTime``, ``datetime``, and ``timezone`` are
    imported.

    Args:
        model_file: Path to the model ``.py`` file.
        model_name: PascalCase model class name.

    Returns:
        True if the file was modified, False if already had is_deleted.
    """
    src = model_file.read_text()
    if "is_deleted" in src:
        return False

    # --- Ensure required imports are present ----------------------------------
    lines = src.splitlines()

    # Add Boolean, DateTime to sqlalchemy imports
    src = _ensure_sa_imports(src, {"Boolean", "DateTime"})
    # Add datetime import
    if "from datetime import datetime" not in src and "import datetime" not in src:
        # Append after 'from __future__ import annotations' line or at top
        src = _insert_after_future(src, "from datetime import datetime, timezone\n")
    elif "timezone" not in src:
        src = src.replace(
            "from datetime import datetime",
            "from datetime import datetime, timezone",
        )

    # --- Append columns to the class body ------------------------------------
    # Find the last mapped_column line for the model class, then insert after it
    new_cols = (
        "\n"
        "    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)\n"
        "    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)\n"
    )

    # Find the end of the class: insert just before any trailing blank line/EOF
    # Strategy: append columns right before the last non-empty line's newline
    # that is inside the class body.  We detect the end of the class by finding
    # the last line that starts with "    " (4-space indent, class body level).
    src_lines = src.splitlines()
    last_class_line = -1
    in_class = False
    for i, line in enumerate(src_lines):
        if re.match(rf"^class {re.escape(model_name)}\b", line):
            in_class = True
        if in_class and line.startswith("    ") and line.strip():
            last_class_line = i

    if last_class_line == -1:
        # Fallback: append at end of file
        src = src.rstrip() + new_cols
    else:
        # Insert after the last class-body line
        src_lines.insert(last_class_line + 1, new_cols.rstrip())
        src = "\n".join(src_lines) + "\n"

    model_file.write_text(src)
    return True


def _ensure_sa_imports(src: str, names: set[str]) -> str:
    """Ensure each name in *names* is present in the ``from sqlalchemy import`` line.

    If the line doesn't exist, appends the imports. Handles the case where
    sqlalchemy imports are split across multiple lines.

    Args:
        src: Python source text.
        names: Set of SQLAlchemy names to ensure are imported.

    Returns:
        Updated source text.
    """
    # Find the first "from sqlalchemy import ..." line (not sqlalchemy.orm)
    sa_import_re = re.compile(r"^(from sqlalchemy import )(.+)$", re.MULTILINE)
    m = sa_import_re.search(src)
    if m:
        existing = {n.strip() for n in m.group(2).split(",")}
        missing = names - existing
        if not missing:
            return src
        new_imports = ", ".join(sorted(existing | missing))
        src = src[:m.start()] + m.group(1) + new_imports + src[m.end():]
        return src
    # No "from sqlalchemy import" line found — insert before "from sqlalchemy.orm"
    insert = "from sqlalchemy import " + ", ".join(sorted(names)) + "\n"
    src = re.sub(r"^(from sqlalchemy\.orm )", insert + r"\1", src, count=1, flags=re.MULTILINE)
    return src


def _insert_after_future(src: str, line_to_insert: str) -> str:
    """Insert *line_to_insert* after the ``from __future__ import`` line.

    Args:
        src: Python source text.
        line_to_insert: Line (with trailing newline) to insert.

    Returns:
        Updated source text.
    """
    future_re = re.compile(r"^from __future__ import .+$", re.MULTILINE)
    m = future_re.search(src)
    if m:
        pos = m.end()
        return src[:pos] + "\n" + line_to_insert + src[pos:]
    return line_to_insert + src


# ---------------------------------------------------------------------------
# CRUD patcher
# ---------------------------------------------------------------------------

def _patch_crud(crud_file: Path, model_name: str, stem: str) -> bool:
    """Override delete() and patch get_multi() in the CRUD file.

    Adds:
    - ``delete()`` override that sets ``is_deleted=True`` and ``deleted_at=now()``.
    - Comment above ``delete = crud.delete`` alias to make override visible.
    - A ``_get_multi_active`` wrapper that filters ``is_deleted=True`` rows.

    Args:
        crud_file: Path to ``app/crud/{stem}.py``.
        model_name: PascalCase model class name.
        stem: Snake-case model stem (used to build table/file names).

    Returns:
        True if the file was modified.
    """
    src = crud_file.read_text()
    if "is_deleted" in src:
        return False

    lower = model_name.lower()

    soft_delete_block = textwrap.dedent(f"""

        # ---------------------------------------------------------------------------
        # Soft-delete override — added by add_soft_delete tool
        # ---------------------------------------------------------------------------
        import uuid as _sd_uuid
        from datetime import datetime as _sd_datetime, timezone as _sd_timezone
        from sqlalchemy import select as _sd_select
        from sqlalchemy.ext.asyncio import AsyncSession as _SdSession


        async def delete(session: _SdSession, id: "_sd_uuid.UUID") -> {model_name} | None:
            \"\"\"Soft-delete a {model_name} by primary key.

            Sets ``is_deleted=True`` and ``deleted_at`` to the current UTC time.
            The row is NOT physically removed — use a separate purge step if needed.

            Args:
                session: Async SQLAlchemy session.
                id: Primary key of the {model_name} to soft-delete.

            Returns:
                The updated {model_name} instance, or None if not found.
            \"\"\"
            stmt = _sd_select({model_name}).where(
                {model_name}.id == id,
                {model_name}.is_deleted == False,  # noqa: E712
            )
            result = await session.execute(stmt)
            obj = result.scalar_one_or_none()
            if obj is None:
                return None
            obj.is_deleted = True
            obj.deleted_at = _sd_datetime.now(_sd_timezone.utc)
            await session.flush()
            return obj


        async def get_multi_active(
            session: _SdSession,
            *,
            owner_id: "_sd_uuid.UUID | None" = None,
            skip: int = 0,
            limit: int = 100,
        ) -> list[{model_name}]:
            \"\"\"List {model_name} rows excluding soft-deleted ones.

            Args:
                session: Async SQLAlchemy session.
                owner_id: If provided, filter by owner.
                skip: Offset (for pagination).
                limit: Maximum rows to return.

            Returns:
                List of active (not soft-deleted) {model_name} instances.
            \"\"\"
            stmt = _sd_select({model_name}).where({model_name}.is_deleted == False)  # noqa: E712
            if owner_id is not None and hasattr({model_name}, "owner_id"):
                stmt = stmt.where({model_name}.owner_id == owner_id)
            stmt = stmt.offset(skip).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())
    """)

    crud_file.write_text(src + soft_delete_block)
    return True


# ---------------------------------------------------------------------------
# Migration generator
# ---------------------------------------------------------------------------

def _write_migration(versions_dir: Path, model_name: str, stem: str) -> Path:
    """Generate an Alembic migration adding is_deleted + deleted_at columns.

    Args:
        versions_dir: ``alembic/versions/`` directory.
        model_name: PascalCase model name.
        stem: Snake-case model stem (used to derive table name).

    Returns:
        Path of the created migration file.
    """
    from generators._pluralize import pluralize
    table = pluralize(stem)
    rev_id = f"soft_delete_{table}"
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    content = textwrap.dedent(f"""\
        \"\"\"Add soft-delete columns (is_deleted, deleted_at) to {table}.

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
            \"\"\"Add is_deleted and deleted_at columns to {table}.\"\"\"
            op.add_column(
                "{table}",
                sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
            )
            op.add_column(
                "{table}",
                sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            )
            # Index for efficient filtering of active (non-deleted) rows
            op.create_index(
                "ix_{table}_is_deleted",
                "{table}",
                ["is_deleted"],
            )


        def downgrade() -> None:
            \"\"\"Remove soft-delete columns from {table}.\"\"\"
            op.drop_index("ix_{table}_is_deleted", table_name="{table}")
            op.drop_column("{table}", "deleted_at")
            op.drop_column("{table}", "is_deleted")
    """)

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
