"""TOOL-001: add_soft_delete — add real soft-delete to a FastAPI/SQLAlchemy project.

What this tool actually does (end-to-end):

1. Discovers all domain models in ``app/models/`` (using AST to read real class
   names — not filename-derived guesses).
2. Injects ``is_deleted`` + ``deleted_at`` columns into each model file that
   doesn't already have them.
3. **Patches the shared ``CRUDBase`` class in ``app/crud/base.py``** so its
   ``get()`` / ``get_multi()`` / ``delete()`` methods are soft-delete-aware
   *in place* — when the bound model has an ``is_deleted`` column, deletes
   flip the flag (instead of physically removing the row) and reads filter
   soft-deleted rows out automatically.
4. Generates an Alembic migration adding the two columns to each affected table.

CONTRACT §B1.0 + §B1.0.1 pattern (mirrors ``add_graceful_shutdown``):

The tool is idempotent: a second run detects the ``SOFT_DELETE_PATCH_APPLIED``
fingerprint in ``app/crud/base.py`` and returns ``status="no_op"`` without
touching any file.

P1-#14 RESOLUTION (vs. previous version): the old implementation wrote
per-model module-level shadow functions (``get``/``get_multi``/``delete``)
that *appeared* to override the CRUDBase re-export aliases, plus an orphan
UnitOfWork "glue module" at ``app/soft_delete.py`` that nothing imported.
Soft-delete worked by accident through the shadow; the actual ``CRUDBase``
instance stayed hard-delete, and the UoW primitive was dead weight.  This
rewrite patches ``CRUDBase`` directly (single source of truth) and drops the
orphan UoW emission entirely.

BUG C FIX (preserved): the column injection + migration emission remain the
honest fix for the older "success-but-inert" failure mode.
"""

from __future__ import annotations

import ast
import re
import textwrap
import time
from pathlib import Path

from adapt._base import patch_append_module_block
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

MCP_TOOL = {
    "name": "fastapi_data_add_soft_delete",
    "description": (
        "Inject is_deleted + deleted_at columns into domain models, patch the "
        "shared CRUDBase class so get/get_multi/delete are soft-delete-aware "
        "in place, and emit an Alembic migration per affected table."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_soft_delete",
}


# Fingerprint substring used to detect that ``app/crud/base.py`` has already
# been patched with the soft-delete-aware overrides (drives idempotency).
_PATCH_FINGERPRINT = "SOFT_DELETE_PATCH_APPLIED"


# Module-level block appended to ``app/crud/base.py`` to make ``CRUDBase``
# soft-delete-aware. We override the three methods by assignment at module
# scope rather than editing the class body — this keeps the patch additive
# and AST-safe.
_CRUDBASE_PATCH = '''

# ---------------------------------------------------------------------------
# SOFT_DELETE_PATCH_APPLIED — added by add_soft_delete tool.
# ---------------------------------------------------------------------------
# Single source of truth: CRUDBase.get / get_multi / delete become
# soft-delete-aware in place. When the bound model has an ``is_deleted``
# column, reads exclude soft-deleted rows and ``delete()`` flips the flag
# (and ``deleted_at`` if present) instead of physically removing the row.
# Models without ``is_deleted`` keep the original hard-delete behaviour, so
# auth / infra tables stay untouched.
from datetime import datetime as _sd_datetime, timezone as _sd_timezone

from sqlalchemy import func as _sd_func, select as _sd_select


async def _sd_get(self, session, id):
    """Soft-delete-aware ``get`` — returns ``None`` for soft-deleted rows."""
    stmt = _sd_select(self.model).where(self.model.id == id)
    if hasattr(self.model, "is_deleted"):
        stmt = stmt.where(self.model.is_deleted == False)  # noqa: E712
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _sd_get_multi(self, session, *, skip=0, limit=20, owner_id=None):
    """Soft-delete-aware ``get_multi`` — excludes soft-deleted rows."""
    stmt = _sd_select(self.model)
    if hasattr(self.model, "is_deleted"):
        stmt = stmt.where(self.model.is_deleted == False)  # noqa: E712
    if owner_id is not None and hasattr(self.model, "owner_id"):
        stmt = stmt.where(self.model.owner_id == owner_id)
    count_stmt = _sd_select(_sd_func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = stmt.order_by(self.model.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return {"data": list(result.scalars().all()), "count": total}


async def _sd_delete(self, session, id):
    """Soft-delete-aware ``delete``.

    For models with ``is_deleted``: flips ``is_deleted=True`` (and
    ``deleted_at`` if present) instead of issuing a SQL DELETE.
    For models without it: falls back to the original hard-delete.
    """
    obj = await _sd_get(self, session, id)
    if obj is None:
        return None
    if hasattr(obj, "is_deleted"):
        obj.is_deleted = True
        if hasattr(obj, "deleted_at"):
            obj.deleted_at = _sd_datetime.now(_sd_timezone.utc)
        await session.flush()
        return obj
    await session.delete(obj)
    await session.flush()
    return obj


CRUDBase.get = _sd_get
CRUDBase.get_multi = _sd_get_multi
CRUDBase.delete = _sd_delete
'''


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def add_soft_delete(inp: ToolInput) -> ToolResult:
    """Add real soft-delete capability to a FastAPI/SQLAlchemy project.

    Discovers domain models, injects ``is_deleted`` / ``deleted_at`` columns,
    patches the shared ``CRUDBase`` in ``app/crud/base.py`` to be
    soft-delete-aware in place, and emits an Alembic migration per affected
    table. **No** per-model CRUD module is shadowed, and **no** orphan UoW
    glue file is written.

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

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

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
    crud_base_file = app_dir / "crud" / "base.py"

    # Idempotency check: CRUDBase patch fingerprint present in app/crud/base.py.
    if _soft_delete_already_installed(crud_base_file):
        return ToolResult(
            status="no_op",
            notes=[
                "Soft-delete already installed — CRUDBase patch fingerprint present in app/crud/base.py."
            ],
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
                "[dry_run] Would patch CRUDBase in app/crud/base.py so get/get_multi/delete are soft-delete-aware.",
                "[dry_run] Would generate Alembic migration for each model.",
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []

    # --- Step 1: Patch models (inject is_deleted + deleted_at) ---------------
    patched_models: list[str] = []
    versions_dir = project / "alembic" / "versions"

    for stem, pascal in model_pairs:
        model_file = app_dir / "models" / f"{stem}.py"

        if model_file.exists() and _patch_model(model_file, pascal):
            files_modified.append(str(model_file))
            patched_models.append(pascal)

        # Generate migration
        if versions_dir.exists():
            mig = _write_migration(versions_dir, pascal, stem)
            files_created.append(str(mig))

    # --- Step 2: Patch CRUDBase (single source of truth) ---------------------
    if crud_base_file.exists() and patch_append_module_block(
        crud_base_file,
        block=_CRUDBASE_PATCH,
        fingerprint=_PATCH_FINGERPRINT,
    ):
        files_modified.append(str(crud_base_file))

    # --- Step 3: Syntax-check all written files ------------------------------
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
            "Patched app/crud/base.py: CRUDBase.get/get_multi/delete are now soft-delete-aware.",
            "  - get()/get_multi() filter out is_deleted=True rows.",
            "  - delete() flips is_deleted/deleted_at instead of issuing SQL DELETE.",
            "  - Models without is_deleted (auth/infra) keep original hard-delete behaviour.",
            "Alembic migration generated for each patched model.",
        ],
        next_steps=[
            "alembic upgrade head",
            "In routes: keep using the existing crud.delete/get/get_multi entry points — they now soft-delete automatically.",
            "Soft-deleted rows are excluded from get_multi() list/get responses.",
            "To hard-delete, issue a direct SQL DELETE or add a dedicated purge endpoint.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------


def _soft_delete_already_installed(crud_base_file: Path) -> bool:
    """Return True if the CRUDBase soft-delete patch fingerprint is present.

    Args:
        crud_base_file: Path to ``app/crud/base.py``.

    Returns:
        True if soft-delete is already installed (fingerprint present).
    """
    if not crud_base_file.exists():
        return False
    return _PATCH_FINGERPRINT in crud_base_file.read_text()


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
    skip = {"base", "user", "mixins", "__init__", "tenant"}
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
            n.name
            for n in ast.walk(tree)
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
    # Determine which names are ALREADY imported from sqlalchemy via AST so we
    # correctly handle both single-line (`from sqlalchemy import A, B`) and
    # parenthesized multi-line (`from sqlalchemy import (\n  A,\n  B,\n)`) forms.
    try:
        already: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                already |= {alias.name for alias in node.names}
        missing = names - already
    except SyntaxError:
        missing = names  # best-effort if the source is already non-parseable
    if not missing:
        return src
    # Add the missing names as a SEPARATE, always-valid import line placed just
    # before the first existing sqlalchemy import (a second from-import is fine).
    insert = "from sqlalchemy import " + ", ".join(sorted(missing)) + "\n"
    anchor = re.search(r"^from sqlalchemy import ", src, flags=re.MULTILINE) or re.search(
        r"^from sqlalchemy\.orm ", src, flags=re.MULTILINE
    )
    if anchor:
        return src[: anchor.start()] + insert + src[anchor.start() :]
    return insert + src


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
