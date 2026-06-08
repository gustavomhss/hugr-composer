"""TOOL-001: add_soft_delete — real soft-delete for FastAPI/SQLAlchemy.

Discovers domain models, injects ``is_deleted`` + ``deleted_at`` columns,
patches the shared ``CRUDBase`` in ``app/crud/base.py`` (single source of
truth — P1-#14) so ``get/get_multi/delete`` are soft-delete-aware in place,
and emits an Alembic migration per affected table. Per-model opt-out hook
(F-04): a model without ``is_deleted`` falls through to hard-delete, so
auth/infra tables keep hard-delete semantics. Idempotent via the
``SOFT_DELETE_PATCH_APPLIED`` fingerprint.
"""

from __future__ import annotations

import ast
import re
import time
from pathlib import Path

from adapt._base import (
    patch_append_module_block,
    patch_append_router_endpoint,
    render,
    render_to,
)
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

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

# Fingerprint for the soft-delete management endpoints appended to each
# domain model's route file (restore / permanent-delete / list-deleted).
_ROUTES_FINGERPRINT = "SOFT_DELETE_ROUTES_APPLIED"


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
    patched_models: list[str] = []
    versions_dir = project / "alembic" / "versions"

    routes_dir = app_dir / "api" / "routes"
    for stem, pascal in model_pairs:
        model_file = app_dir / "models" / f"{stem}.py"
        if model_file.exists() and _patch_model(model_file, pascal):
            files_modified.append(str(model_file))
            patched_models.append(pascal)
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
            f"Injected is_deleted + deleted_at columns into models: {model_summary}.",
            "Patched app/crud/base.py: CRUDBase.get/get_multi/delete are now soft-delete-aware.",
            "  - get()/get_multi() filter out is_deleted=True rows.",
            "  - delete() flips is_deleted/deleted_at instead of issuing SQL DELETE.",
            "  - Models without is_deleted (auth/infra) keep original hard-delete behaviour.",
            "Added management routes per model: GET /deleted/, POST /{id}/restore, "
            "DELETE /{id}/permanent (auth-guarded, owner-scoped).",
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


def _patch_routes(route_file: Path, stem: str, pascal: str) -> bool:
    """Append soft-delete management endpoints to a model's route file.

    Adds ``GET /deleted/``, ``POST /{id}/restore`` and
    ``DELETE /{id}/permanent`` to ``app/api/routes/<stem>.py``. Idempotent
    via the ``SOFT_DELETE_ROUTES_APPLIED`` fingerprint. Returns ``True`` when
    the block is appended, ``False`` when it was already present.
    """
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
    """Return ``(snake_stem, PascalName)`` pairs from ``app/models/``."""
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


def _patch_model(model_file: Path, model_name: str) -> bool:
    """Inject ``is_deleted`` and ``deleted_at`` columns into the model class."""
    src = model_file.read_text()
    if "is_deleted" in src:
        return False

    src = _ensure_sa_imports(src, {"Boolean", "DateTime"})
    if "from datetime import datetime" not in src and "import datetime" not in src:
        src = _insert_after_future(src, "from datetime import datetime, timezone\n")
    elif "timezone" not in src:
        src = src.replace(
            "from datetime import datetime",
            "from datetime import datetime, timezone",
        )

    new_cols = (
        "\n"
        "    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)\n"
        "    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)\n"
    )

    src_lines = src.splitlines()
    last_class_line = -1
    in_class = False
    for i, line in enumerate(src_lines):
        if re.match(rf"^class {re.escape(model_name)}\b", line):
            in_class = True
        if in_class and line.startswith("    ") and line.strip():
            last_class_line = i

    if last_class_line == -1:
        src = src.rstrip() + new_cols
    else:
        src_lines.insert(last_class_line + 1, new_cols.rstrip())
        src = "\n".join(src_lines) + "\n"

    model_file.write_text(src)
    return True


def _ensure_sa_imports(src: str, names: set[str]) -> str:
    """Ensure each name in *names* is present in the sqlalchemy imports."""
    try:
        already: set[str] = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
                already |= {alias.name for alias in node.names}
        missing = names - already
    except SyntaxError:
        missing = names
    if not missing:
        return src
    insert = "from sqlalchemy import " + ", ".join(sorted(missing)) + "\n"
    anchor = re.search(r"^from sqlalchemy import ", src, flags=re.MULTILINE) or re.search(
        r"^from sqlalchemy\.orm ", src, flags=re.MULTILINE
    )
    if anchor:
        return src[: anchor.start()] + insert + src[anchor.start() :]
    return insert + src


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


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
