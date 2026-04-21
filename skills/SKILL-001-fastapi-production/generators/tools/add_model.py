"""ADAPT tool: add a complete model to an existing FastAPI project.

Orchestrates multiple generators to produce everything needed for a new
domain model — ORM model, CRUD layer, input/output schemas, API routes —
and wires the new model into the existing router registry and Alembic
discovery.

Usage::

    from generators.tools.add_model import add_model

    result = add_model(
        project_dir="/path/to/existing-project",
        name="Product",
        fields={"name": "str", "price": "Decimal", "stock": "int"},
        owner_field="user",
    )
"""

from __future__ import annotations

MCP_TOOL = {
    'name': 'fastapi_meta_add_model',
    'description': 'Add a complete model to an EXISTING project.',
    'tags': ['adapt', 'operate'],
    'entry': 'add_model',
    'annotations': {'readOnlyHint': False},
}

import re
from pathlib import Path

from generators.tools._layout import resolve_app_root

from generators.database.model import generate_model
from generators.database.crud import generate_crud
from generators.schemas.input_schema import generate_input_schema
from generators.schemas.output_schema import generate_output_schema
from generators.schemas.list_response import generate_list_response
from generators.endpoints.crud_routes import generate_crud_routes


def add_model(
    project_dir: str,
    name: str,
    fields: dict[str, str],
    owner_field: str | None = None,
    *,
    auth: str = "required",
    with_soft_delete: bool = False,
) -> dict:
    """Add a complete model to an existing FastAPI project.

    This is a high-level tool that calls individual generators in the
    correct order and then patches existing files (``routes/__init__.py``
    and ``models/__init__.py``) so the new model is fully wired.

    It is safe to run on a project that already has models — existing
    files are never overwritten.  If the model already exists (i.e. the
    model file is already on disk), the operation is skipped and a note
    is returned.

    Args:
        project_dir: Root directory of the existing project (the folder
            that contains ``models/``, ``crud/``, ``schemas/``, etc.).
        name: Model class name in PascalCase (e.g. ``Product``).
        fields: Mapping of field_name -> type hint string.  Accepted
            types: ``str``, ``text``, ``int``, ``float``, ``bool``,
            ``Decimal``, ``date``, ``datetime``, ``EmailStr``, ``email``,
            ``url``, ``uuid``.
        owner_field: If set (e.g. ``"user"``), the model gets an
            ``owner_id`` FK and routes enforce ownership.  Regular users
            may only access their own records; superusers have full
            access.
        auth: Authentication level for routes.  One of ``"required"``,
            ``"superuser"``, ``"public_read"``, or ``"none"``.
        with_soft_delete: Add ``is_deleted`` / ``deleted_at`` columns
            and use soft-delete in the CRUD layer.

    Returns:
        Dict with ``files_created``, ``files_modified``, ``notes``, and
        ``next_steps``.
    """
    root = resolve_app_root(project_dir)
    lower = name.lower()
    cls = name if name[0].isupper() else name.capitalize()

    files_created: list[str] = []
    files_modified: list[str] = []
    notes: list[str] = []
    next_steps: list[str] = []

    # ------------------------------------------------------------------
    # Guard: skip if model already exists
    # ------------------------------------------------------------------
    model_file = root / "models" / f"{lower}.py"
    if model_file.exists():
        return {
            "files_created": [],
            "files_modified": [],
            "notes": [
                f"Model {cls} already exists at {model_file}. Skipped to avoid duplicates."
            ],
            "next_steps": [],
        }

    # ------------------------------------------------------------------
    # 1. Generate ORM model
    # ------------------------------------------------------------------
    result = generate_model(
        output_dir=str(root),
        name=name,
        fields=fields,
        with_timestamps=True,
        with_soft_delete=with_soft_delete,
        owner_field=owner_field,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    # ------------------------------------------------------------------
    # 2. Generate CRUD layer
    # ------------------------------------------------------------------
    # Auto-detect unique field: if any field maps to EmailStr, use it
    unique_field: str | None = None
    for field_name, type_hint in fields.items():
        if type_hint in ("EmailStr", "email"):
            unique_field = field_name
            break

    result = generate_crud(
        output_dir=str(root),
        model_name=name,
        with_owner_filter=owner_field is not None,
        with_soft_delete=with_soft_delete,
        unique_field=unique_field,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    # ------------------------------------------------------------------
    # 3. Generate schemas (input, output, list)
    # ------------------------------------------------------------------
    result = generate_input_schema(
        output_dir=str(root),
        name=name,
        fields=fields,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    result = generate_output_schema(
        output_dir=str(root),
        name=name,
        fields=fields,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    result = generate_list_response(
        output_dir=str(root),
        name=name,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    # ------------------------------------------------------------------
    # 4. Generate CRUD routes
    # ------------------------------------------------------------------
    result = generate_crud_routes(
        output_dir=str(root),
        model_name=name,
        fields=fields,
        auth=auth,
        owner_field=owner_field,
    )
    files_created.extend(result["files_created"])
    notes.extend(result.get("notes", []))

    # ------------------------------------------------------------------
    # 5. Update router registry (routes/__init__.py)
    # ------------------------------------------------------------------
    routes_init = _find_routes_init(root)
    if routes_init is not None:
        modified = _patch_routes_init(routes_init, lower, cls)
        if modified:
            files_modified.append(str(routes_init))
            notes.append(f"Patched {routes_init.relative_to(root)} with {lower}_router.")
        else:
            notes.append(
                f"{lower}_router already registered in {routes_init.relative_to(root)}."
            )
    else:
        notes.append(
            "Could not find routes/__init__.py — register the router manually."
        )

    # ------------------------------------------------------------------
    # 6. Update models/__init__.py (Alembic discovery)
    # ------------------------------------------------------------------
    models_init = root / "models" / "__init__.py"
    if models_init.exists():
        modified = _patch_models_init(models_init, lower, cls)
        if modified:
            files_modified.append(str(models_init))
            notes.append(f"Patched models/__init__.py with {cls} import for Alembic.")
        else:
            notes.append(f"{cls} already imported in models/__init__.py.")
    else:
        notes.append(
            "models/__init__.py not found — add the model import manually for Alembic."
        )

    # ------------------------------------------------------------------
    # 7. Auto-generate migration for the new model
    # ------------------------------------------------------------------
    # This ensures the model works in staging/production (where create_all
    # is skipped and Alembic is the sole source of truth).
    proj_root = Path(project_dir)
    versions_dir = proj_root / "alembic" / "versions"
    if versions_dir.is_dir():
        try:
            from generators.database.alembic_migration import _table_block
            from generators._pluralize import pluralize as _plural

            table = _plural(lower)
            has_owner = owner_field is not None
            block = _table_block(table, cls, fields, with_owner=has_owner)

            # Deterministic revision ID based on model name
            import hashlib
            rev_id = hashlib.sha256(f"add_{lower}".encode()).hexdigest()[:12]

            # Find the latest existing revision to chain as down_revision
            existing = sorted(versions_dir.glob("*.py"))
            # Get the last revision's ID (from filename prefix)
            down_revision = "None"
            for existing_file in reversed(existing):
                fname = existing_file.stem
                if fname.startswith("0"):
                    # e.g. 0001_initial_schema → revision = "0001_initial"
                    try:
                        content_check = existing_file.read_text()
                        import re as _re
                        match = _re.search(r'^revision[\s:]*(?:str\s*)?=\s*["\']([^"\']+)["\']', content_check, _re.MULTILINE)
                        if match:
                            down_revision = f'"{match.group(1)}"'
                            break
                    except Exception:
                        pass

            migration_content = (
                f'"""Add {lower} table."""\n'
                f'\n'
                f'revision = "{rev_id}"\n'
                f'down_revision = {down_revision}\n'
                f'\n'
                f'import sqlalchemy as sa\n'
                f'from alembic import op\n'
                f'\n'
                f'\n'
                f'def upgrade() -> None:\n'
                f'{block}\n'
                f'\n'
                f'\n'
                f'def downgrade() -> None:\n'
                f'    op.drop_table("{table}")\n'
            )

            migration_file = versions_dir / f"0002_add_{lower}.py"
            # Don't overwrite if exists (idempotent)
            if not migration_file.exists():
                migration_file.write_text(migration_content)
                files_created.append(str(migration_file))
                notes.append(f"Generated migration: alembic/versions/0002_add_{lower}.py")
            else:
                notes.append(f"Migration for {cls} already exists — skipped.")
        except ImportError:
            notes.append("Could not import migration helpers — generate migration manually.")

    next_steps.append(f"Review the migration in alembic/versions/")
    next_steps.append("alembic upgrade head")
    next_steps.append(f"Run tests: pytest tests/ -v -k {lower}")

    return {
        "files_created": files_created,
        "files_modified": files_modified,
        "notes": notes,
        "next_steps": next_steps,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_routes_init(root: Path) -> Path | None:
    """Locate the routes ``__init__.py`` that contains ``api_router``.

    The orchestrator writes this file to ``routes/__init__.py`` but some
    projects may use ``api/routes/__init__.py``.  We check both and
    pick whichever contains ``api_router``.
    """
    candidates = [
        root / "routes" / "__init__.py",
        root / "api" / "routes" / "__init__.py",
    ]
    for candidate in candidates:
        if candidate.exists():
            content = candidate.read_text()
            if "api_router" in content:
                return candidate
    # Fallback: return whichever exists, even without api_router
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _patch_routes_init(routes_init: Path, lower: str, cls: str) -> bool:
    """Append a new router import + include_router to ``routes/__init__.py``.

    Returns True if the file was modified, False if the router was
    already registered.
    """
    content = routes_init.read_text()

    # Guard: already registered
    router_var = f"{lower}_router"
    if router_var in content:
        return False

    import_line = f"from app.api.routes.{lower} import router as {router_var}"
    include_line = f"api_router.include_router({router_var})"

    lines = content.rstrip("\n").split("\n")

    # Strategy: insert the import after the last existing "from app..."
    # import, and append the include_router at the end.
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("from app.") and "import" in stripped:
            last_import_idx = i

    if last_import_idx >= 0:
        lines.insert(last_import_idx + 1, import_line)
    else:
        # No existing app imports — insert after the last top-level import
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("from ", "import ")):
                insert_idx = i + 1
        lines.insert(insert_idx, import_line)

    # Append include_router before the final empty line (if any)
    # Find the last non-empty line
    last_non_empty = len(lines) - 1
    while last_non_empty > 0 and lines[last_non_empty].strip() == "":
        last_non_empty -= 1

    lines.insert(last_non_empty + 1, include_line)

    routes_init.write_text("\n".join(lines) + "\n")
    return True


def _patch_models_init(models_init: Path, lower: str, cls: str) -> bool:
    """Append a model import to ``models/__init__.py`` for Alembic discovery.

    Returns True if the file was modified, False if the import already
    exists.
    """
    content = models_init.read_text()

    import_line = f"from app.models.{lower} import {cls}  # noqa: F401"

    # Guard: already imported
    if f"from app.models.{lower} import {cls}" in content:
        return False

    lines = content.rstrip("\n").split("\n")

    # Append the import at the end, before any trailing blank lines
    last_non_empty = len(lines) - 1
    while last_non_empty > 0 and lines[last_non_empty].strip() == "":
        last_non_empty -= 1

    lines.insert(last_non_empty + 1, import_line)

    models_init.write_text("\n".join(lines) + "\n")
    return True
