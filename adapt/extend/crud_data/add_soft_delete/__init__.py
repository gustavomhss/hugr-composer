"""TOOL-001: add_soft_delete — real soft-delete for FastAPI/SQLAlchemy.

Implements the SPEC v2 design (specs/TOOL-001-add_soft_delete.md):

  * Emits ``app/models/mixins.py::SoftDeleteMixin`` (is_deleted, deleted_at,
    deleted_by) and makes each domain model inherit it.
  * Emits ``app/core/soft_delete_filter.py`` — a global ``do_orm_execute``
    listener using ``with_loader_criteria`` so every SELECT against a
    SoftDeleteMixin model transparently excludes soft-deleted rows
    (INV-SD-01); wired into ``app/main.py`` as a side-effect import.
  * Adds ``soft_delete`` / ``restore`` / ``hard_delete`` / ``list_deleted``
    helpers to ``app/crud/<model>.py`` — restore atomically clears all three
    deletion columns (INV-SD-04); soft_delete uses ``flush`` not ``commit``.
  * Adds the admin-only ``<Model>DeletedPublic`` / ``<Model>sDeletedPublic``
    schemas to ``app/schemas/<model>.py``; ``<Model>Public`` is never
    modified, so the default API contract stays clean (INV-SD-08).
  * Patches ``CRUDBase.delete`` so the default DELETE route soft-deletes,
    adds management routes, and emits an Alembic migration per table.

Per-model opt-out (F-04): a model without ``is_deleted`` keeps hard-delete.
Idempotent via the ``SOFT_DELETE_PATCH_APPLIED`` fingerprint in
``app/crud/base.py``.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

from adapt._base import (
    load_template,
    patch_add_import,
    patch_append_module_block,
    patch_append_router_endpoint,
    render,
    render_to,
)
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_soft_delete",
    "description": (
        "Add spec-compliant soft-delete: a SoftDeleteMixin (is_deleted, "
        "deleted_at, deleted_by), a global do_orm_execute query filter, "
        "soft_delete/restore/hard_delete CRUD helpers, admin deletion schemas "
        "and routes, and an Alembic migration per affected table."
    ),
    "tags": ["extend", "crud_data"],
    "entry": "add_soft_delete",
    "imports_primitives": [],
    "imports_adapters": [],

}

# Fingerprint substring used to detect that ``app/crud/base.py`` has already
# been patched with the soft-delete-aware overrides (drives idempotency).
_PATCH_FINGERPRINT = "SOFT_DELETE_PATCH_APPLIED"

# Fingerprint for the soft-delete management endpoints appended to each
# domain model's route file (restore / permanent-delete / list-deleted).
_ROUTES_FINGERPRINT = "SOFT_DELETE_ROUTES_APPLIED"

# Fingerprint for the CRUD helpers (soft_delete/restore/hard_delete/list_deleted)
# appended to each domain model's ``app/crud/<model>.py``.
_CRUD_FINGERPRINT = "SOFT_DELETE_CRUD_APPLIED"

# Fingerprint for the admin deletion schemas appended to ``app/schemas/<model>.py``.
_SCHEMA_FINGERPRINT = "SOFT_DELETE_SCHEMA_APPLIED"


def add_soft_delete(inp: ToolInput) -> ToolResult:
    """Add real soft-delete capability to a FastAPI/SQLAlchemy project."""
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

    if _soft_delete_already_installed(crud_base_file):
        return ToolResult(
            status="no_op",
            notes=[
                "Soft-delete already installed — CRUDBase patch fingerprint present in app/crud/base.py."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    model_pairs = _discover_models(app_dir)

    if inp.dry_run:
        model_names = [pascal for _, pascal in model_pairs] if model_pairs else ["(none found)"]
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would make models inherit SoftDeleteMixin "
                "(is_deleted, deleted_at, deleted_by): " + ", ".join(model_names),
                "[dry_run] Would emit app/models/mixins.py + app/core/soft_delete_filter.py "
                "(global do_orm_execute filter) and wire it into app/main.py.",
                "[dry_run] Would add soft_delete/restore/hard_delete/list_deleted crud helpers, "
                "admin schemas, management routes, and patch CRUDBase.delete.",
                "[dry_run] Would generate an Alembic migration for each model.",
            ],
            next_steps=["Re-run without dry_run=True to apply."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    files_modified: list[str] = []
    patched_models: list[str] = []
    versions_dir = project / "alembic" / "versions"

    # Global, project-wide artefacts (emitted once regardless of model count):
    # the SoftDeleteMixin and the do_orm_execute query filter, plus the
    # side-effect import that activates the filter at startup.
    _emit_mixin(app_dir, files_created)
    _emit_filter(app_dir, files_created)
    if _wire_filter_into_main(app_dir):
        files_modified.append(str(app_dir / "main.py"))

    routes_dir = app_dir / "api" / "routes"
    crud_dir = app_dir / "crud"
    schemas_dir = app_dir / "schemas"
    for stem, pascal in model_pairs:
        model_file = app_dir / "models" / f"{stem}.py"
        if model_file.exists() and _patch_model(model_file, pascal):
            files_modified.append(str(model_file))
            patched_models.append(pascal)
        crud_file = crud_dir / f"{stem}.py"
        if crud_file.exists() and _patch_crud(crud_file, stem, pascal):
            files_modified.append(str(crud_file))
        schema_file = schemas_dir / f"{stem}.py"
        if schema_file.exists() and _patch_schema(schema_file, stem, pascal):
            files_modified.append(str(schema_file))
        route_file = routes_dir / f"{stem}.py"
        if route_file.exists() and _patch_routes(route_file, stem, pascal):
            files_modified.append(str(route_file))
        if versions_dir.exists():
            mig = _write_migration(versions_dir, pascal, stem)
            files_created.append(str(mig))

    crudbase_patch = render(_HERE, "crudbase_patch.py.tmpl", {})
    if crud_base_file.exists() and patch_append_module_block(
        crud_base_file,
        block=crudbase_patch,
        fingerprint=_PATCH_FINGERPRINT,
    ):
        files_modified.append(str(crud_base_file))

    _emit_project_test(project, files_created)

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
            f"Models now inherit SoftDeleteMixin (is_deleted, deleted_at, deleted_by): {model_summary}.",
            "Emitted app/models/mixins.py::SoftDeleteMixin.",
            "Emitted app/core/soft_delete_filter.py — a global do_orm_execute "
            "listener with with_loader_criteria so EVERY SELECT excludes "
            "soft-deleted rows (INV-SD-01); wired into app/main.py.",
            "Added crud helpers per model: soft_delete (sets is_deleted/deleted_at/"
            "deleted_by + flush), restore (clears all 3 columns), hard_delete, "
            "list_deleted (include_deleted=True).",
            "Added admin schemas <Model>DeletedPublic / <Model>sDeletedPublic; "
            "<Model>Public is intentionally NOT modified and does NOT expose the "
            "deletion columns (INV-SD-08).",
            "Patched app/crud/base.py: CRUDBase.delete now soft-deletes instead "
            "of issuing SQL DELETE. Models without is_deleted keep hard-delete.",
            "Added management routes per model: GET /deleted/, POST /{id}/restore, "
            "DELETE /{id}/permanent (superuser-gated).",
            "Alembic migration generated for each patched model.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Reads exclude soft-deleted rows automatically via the global filter; "
            "the default DELETE route now soft-deletes.",
            "Pass execution_options(include_deleted=True) for admin/restore queries.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _patch_routes(route_file: Path, stem: str, pascal: str) -> bool:
    """Append soft-delete management endpoints to a model's route file.

    Adds ``GET /deleted/``, ``POST /{id}/restore`` and
    ``DELETE /{id}/permanent`` to ``app/api/routes/<stem>.py``. Idempotent
    via the ``SOFT_DELETE_ROUTES_APPLIED`` fingerprint. Returns ``True`` when
    the block is appended, ``False`` when it was already present.
    """
    if _ROUTES_FINGERPRINT in route_file.read_text():
        return False

    # Ensure the names referenced by the appended handlers are importable.
    src = route_file.read_text()
    if not re.search(r"^import uuid\b", src, flags=re.MULTILINE):
        route_file.write_text(_insert_after_imports(src, "import uuid\n"))
    patch_add_import(route_file, module="fastapi", name="HTTPException")
    patch_add_import(route_file, module="fastapi", name="Query")
    patch_add_import(route_file, module="fastapi", name="status")
    patch_add_import(route_file, module="app.api.deps", name="CurrentSuperuser")
    patch_add_import(route_file, module="app.schemas.message", name="Message")
    # restore route's response_model is the model's base public schema.
    patch_add_import(route_file, module=f"app.schemas.{stem}", name=f"{pascal}Public")

    block = render(
        _HERE,
        "routes_patch.py.tmpl",
        {"STEM": stem, "MODEL": pascal},
    )
    return patch_append_router_endpoint(
        route_file,
        endpoint_block=block,
        fingerprint=_ROUTES_FINGERPRINT,
    )


def _soft_delete_already_installed(crud_base_file: Path) -> bool:
    if not crud_base_file.exists():
        return False
    return _PATCH_FINGERPRINT in crud_base_file.read_text()


def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs for standard CRUD models.

    A model qualifies only if it has BOTH a route file AND a public read schema
    ``<Pascal>Public`` in ``app/schemas/<stem>.py``. The management routes this
    tool appends import ``app.schemas.<stem>.<Pascal>Public``, so a model lacking
    that schema (e.g. add_mfa's MFADevice, whose routes define schemas inline and
    never emit app/schemas/mfa.py) would otherwise get management routes that
    import a non-existent symbol — ModuleNotFoundError: No module named
    'app.schemas.mfa' at boot. Requiring the schema scopes soft-delete to the
    business CRUD models it was designed for.
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    schemas_dir = app_dir / "schemas"
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
        if not base_subclasses:
            continue
        pascal = base_subclasses[0]
        # Require the standard <Pascal>Public read schema; the management routes
        # import it. Models without it (auth-infra models like MFADevice) are out
        # of scope for soft-delete management.
        schema_file = schemas_dir / f"{stem}.py"
        if not schema_file.exists() or f"{pascal}Public" not in schema_file.read_text():
            continue
        pairs.append((stem, pascal))

    return pairs


def _patch_model(model_file: Path, model_name: str) -> bool:
    """Make the model inherit ``SoftDeleteMixin`` (which adds the 3 columns).

    The deletion columns live on :class:`SoftDeleteMixin` (emitted to
    ``app/models/mixins.py``) so the global ``do_orm_execute`` listener can key
    off that single base class via ``with_loader_criteria``. We rewrite the
    target class's bases to ``class <Model>(SoftDeleteMixin, Base):`` and add
    the mixin import. Idempotent: a no-op once the mixin is already a base.
    """
    src = model_file.read_text()
    if "SoftDeleteMixin" in src or "is_deleted" in src:
        return False

    # Insert ``from app.models.mixins import SoftDeleteMixin`` after the Base import.
    if "from app.models.mixins import SoftDeleteMixin" not in src:
        base_import = re.search(r"^from app\.models\.base import .+$", src, flags=re.MULTILINE)
        if base_import:
            pos = base_import.end()
            src = src[:pos] + "\nfrom app.models.mixins import SoftDeleteMixin" + src[pos:]
        else:
            src = _insert_after_future(src, "from app.models.mixins import SoftDeleteMixin\n")

    # Rewrite the class bases: ``class Model(Base)`` -> ``class Model(SoftDeleteMixin, Base)``.
    pattern = re.compile(rf"^(class {re.escape(model_name)}\s*\()([^)]*)\)", re.MULTILINE)

    def _add_mixin(m: re.Match) -> str:
        bases = m.group(2).strip()
        if not bases:
            new_bases = "SoftDeleteMixin"
        elif "SoftDeleteMixin" in bases:
            new_bases = bases
        else:
            new_bases = "SoftDeleteMixin, " + bases
        return f"{m.group(1)}{new_bases})"

    new_src, n = pattern.subn(_add_mixin, src)
    if n == 0:
        return False

    model_file.write_text(new_src)
    return True


def _emit_mixin(app_dir: Path, created: list[str]) -> None:
    """Emit ``app/models/mixins.py`` with the SoftDeleteMixin (once).

    APPEND-safe: ``app/models/mixins.py`` is a shared file — other tools (e.g.
    add_multi_tenancy's TenantScopedMixin) emit their own mixin into it. A naive
    ``render_to`` would OVERWRITE the whole file and silently drop a sibling
    mixin, breaking ``from app.models.mixins import TenantScopedMixin`` at boot
    whenever multi_tenancy was applied before soft_delete. So when the file
    already exists we append only the missing imports + the SoftDeleteMixin
    class, preserving whatever is already there.
    """
    dest = app_dir / "models" / "mixins.py"
    if dest.exists() and "SoftDeleteMixin" in dest.read_text():
        return
    if not dest.exists():
        render_to(_HERE, "mixin.py.tmpl", dest=dest, substitutions={})
        created.append(str(dest))
        return
    # File exists (another mixin lives here) → append without clobbering.
    existing = dest.read_text()
    needed_imports = [
        "import uuid",
        "from datetime import datetime",
        "from sqlalchemy import Boolean, DateTime, ForeignKey, Uuid",
        "from sqlalchemy.orm import Mapped, declared_attr, mapped_column",
    ]
    full = load_template(_HERE, "mixin.py.tmpl").template
    # Pull just the class definition (from `class SoftDeleteMixin` onward).
    marker = "class SoftDeleteMixin"
    class_body = full[full.index(marker) :]
    to_add = [imp for imp in needed_imports if imp not in existing]
    chunk = ""
    if to_add:
        chunk += "\n" + "\n".join(to_add) + "\n"
    chunk += "\n\n" + class_body
    dest.write_text(existing.rstrip("\n") + "\n" + chunk)
    created.append(str(dest))


def _emit_filter(app_dir: Path, created: list[str]) -> None:
    """Emit ``app/core/soft_delete_filter.py`` with the do_orm_execute listener."""
    dest = app_dir / "core" / "soft_delete_filter.py"
    if dest.exists() and "do_orm_execute" in dest.read_text():
        return
    render_to(_HERE, "soft_delete_filter.py.tmpl", dest=dest, substitutions={})
    created.append(str(dest))


def _wire_filter_into_main(app_dir: Path) -> bool:
    """Add the side-effect import of the filter module to ``app/main.py``.

    Returns ``True`` when ``main.py`` was modified, ``False`` if the import was
    already present or ``main.py`` is missing.
    """
    main_file = app_dir / "main.py"
    if not main_file.exists():
        return False
    src = main_file.read_text()
    if "soft_delete_filter" in src:
        return False
    # Side-effect import (registers the do_orm_execute listener at import).
    # Use `from app.core import soft_delete_filter` rather than
    # `import app.core.soft_delete_filter`: the latter BINDS the name `app` in
    # main.py's namespace. _insert_after_imports drops this after the LAST import,
    # and sibling tools (e.g. add_multi_tenancy) add imports BELOW `app =
    # FastAPI(...)` — so the dotted import would rebind `app` to the package,
    # shadowing the FastAPI instance and breaking the next `app.add_middleware`
    # call. The from-import binds `soft_delete_filter`, never `app`.
    import_line = (
        "from app.core import soft_delete_filter  # noqa: F401  (registers soft-delete filter)\n"
    )
    new_src = _insert_after_imports(src, import_line)
    main_file.write_text(new_src)
    return True


def _insert_after_imports(src: str, line_to_insert: str) -> str:
    """Insert *line_to_insert* after the last top-level import in *src*."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return line_to_insert + src
    last_import_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            end = getattr(node, "end_lineno", node.lineno)
            if end and end > last_import_line:
                last_import_line = end
    lines = src.splitlines(keepends=True)
    if last_import_line == 0:
        return line_to_insert + src
    before = "".join(lines[:last_import_line])
    after = "".join(lines[last_import_line:])
    if not before.endswith("\n"):
        before += "\n"
    return before + line_to_insert + after


def _patch_crud(crud_file: Path, stem: str, pascal: str) -> bool:
    """Append soft_delete / restore / hard_delete / list_deleted to crud/<stem>.py."""
    block = render(_HERE, "crud_patch.py.tmpl", {"STEM": stem, "MODEL": pascal})
    return patch_append_module_block(crud_file, block=block, fingerprint=_CRUD_FINGERPRINT)


def _patch_schema(schema_file: Path, stem: str, pascal: str) -> bool:
    """Append <Model>DeletedPublic / <Model>sDeletedPublic to schemas/<stem>.py.

    ``<Model>Public`` is never modified, so the default API contract keeps
    excluding the deletion columns (INV-SD-08).
    """
    src = schema_file.read_text()
    if f"{pascal}Public" not in src:
        # No base public schema to extend — skip rather than emit a broken class.
        return False
    block = render(_HERE, "schema_patch.py.tmpl", {"STEM": stem, "MODEL": pascal})
    return patch_append_module_block(schema_file, block=block, fingerprint=_SCHEMA_FINGERPRINT)


def _insert_after_future(src: str, line_to_insert: str) -> str:
    future_re = re.compile(r"^from __future__ import .+$", re.MULTILINE)
    m = future_re.search(src)
    if m:
        pos = m.end()
        return src[:pos] + "\n" + line_to_insert + src[pos:]
    return line_to_insert + src


def _write_migration(versions_dir: Path, model_name: str, stem: str) -> Path:
    """Generate an Alembic migration adding is_deleted + deleted_at columns."""
    from generators._pluralize import pluralize

    table = pluralize(stem)
    rev_id = f"soft_delete_{table}"
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    migration_file = versions_dir / f"{rev_id}.py"
    render_to(
        _HERE,
        "migration.py.tmpl",
        dest=migration_file,
        substitutions={"table": table, "rev_id": rev_id, "down_rev": down_rev},
    )
    return migration_file


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into {project}/tests/test_add_soft_delete_emitted.py."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_soft_delete_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_soft_delete_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


