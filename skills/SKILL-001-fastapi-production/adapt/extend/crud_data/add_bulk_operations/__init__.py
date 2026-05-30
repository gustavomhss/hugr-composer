"""TOOL-007: add_bulk_operations — HTTP 207 bulk endpoints for FastAPI.

Generates ``POST /<model>s/bulk``, ``PATCH /<model>s/bulk`` and
``DELETE /<model>s/bulk`` routes backed by SQLAlchemy bulk operations with
both ``all_or_nothing`` (single transaction) and ``best_effort`` (per-item
SAVEPOINT) modes. Optional Redis-backed idempotency cache deduplicates
client retries within a 24 h window.

Idempotent: a second run detects ``IdempotencyCache`` in
``app/core/idempotency.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

DEFAULT_MAX_BATCH: int = 1000

MCP_TOOL = {
    "name": "fastapi_data_add_bulk_operations",
    "description": "Add bulk create/update/delete endpoints for all models.",
    "tags": ["extend", "crud_data"],
    "entry": "add_bulk_operations",
}

_SKIP_MODELS: frozenset[str] = frozenset({"base", "user", "mixins", "__init__", "tenant"})


def add_bulk_operations(inp: ToolInput) -> ToolResult:
    """Add bulk create/update/delete endpoints to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            notes=_PREREQ_NOTES,
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    idempotency_file = app_dir / "core" / "idempotency.py"

    if idempotency_file.exists() and "IdempotencyCache" in idempotency_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["IdempotencyCache already present — bulk operations already enabled."],
            execution_time_ms=_ms(start),
        )

    model_names = _discover_models(app_dir)
    if not model_names:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add bulk operations for: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — idempotency cache (write or merge).
    if not idempotency_file.exists():
        idempotency_file.parent.mkdir(parents=True, exist_ok=True)
        render_to(_HERE, "idempotency.py.tmpl", dest=idempotency_file, substitutions={})
    else:
        src = idempotency_file.read_text()
        if "IdempotencyCache" not in src:
            merge_block = render(_HERE, "idempotency_merge.py.tmpl", {})
            idempotency_file.write_text(src.rstrip("\n") + "\n" + merge_block)
    files_created.append(str(idempotency_file))

    # Steps 2-4 — patch schemas, CRUD, routes per model.
    for model_name in model_names:
        lower = model_name.lower()
        _patch_schema(app_dir / "schemas" / f"{lower}.py", model_name, files_modified)
        _patch_crud(app_dir / "crud" / f"{lower}.py", model_name, files_modified)
        _patch_routes(app_dir / "api" / "routes" / f"{lower}.py", model_name, files_modified)

    # Step 5 — main.py startup wiring.
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file, files_modified)

    # Step 6 — Alembic composite-index migration per model.
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        for model_name in model_names:
            table = model_name.lower() + "s"
            mig_file = versions_dir / f"0007_bulk_ops_index_{table}.py"
            if mig_file.exists():
                continue
            render_to(
                _HERE,
                "migration.py.tmpl",
                dest=mig_file,
                substitutions={"table": table, "down_rev": down_rev},
            )
            files_created.append(str(mig_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Bulk operations enabled for: {', '.join(model_names)}",
            "Routes: POST /bulk (create), PATCH /bulk (update), DELETE /bulk (delete).",
            "All routes return HTTP 207 Multi-Status.",
            "Idempotency-Key header supported via Redis cache (24-hour TTL).",
            f"Hard batch size cap: {DEFAULT_MAX_BATCH} items per request.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in your .env for idempotency cache support.",
            "Restart the application.",
        ],
        execution_time_ms=_ms(start),
    )


_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def _discover_models(app_dir: Path) -> list[str]:
    """Return PascalCase model names whose file stem matches a routable model."""
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    names: list[str] = []
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in _SKIP_MODELS or stem not in available_routes:
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
        names.extend(c for c in base_subclasses if c.lower() == stem)
    return names


def _patch_schema(schema_file: Path, model_name: str, modified: list[str]) -> None:
    """Append BulkRequest/Response/ResultItem schemas to ``app/schemas/<lower>.py``."""
    if not schema_file.exists():
        return
    src = schema_file.read_text()
    if "BulkResponse" in src:
        return
    src = _ensure_pydantic_imports(src)
    schema_file.write_text(
        src
        + render(
            _HERE,
            "schema_addition.py.tmpl",
            {
                "model_name": model_name,
                "lower": model_name.lower(),
                "max_batch": str(DEFAULT_MAX_BATCH),
            },
        )
    )
    modified.append(str(schema_file))


def _ensure_pydantic_imports(src: str) -> str:
    """Ensure BaseModel + ConfigDict + Field + field_validator are all imported."""
    if "field_validator" not in src:
        src = src.replace(
            "from pydantic import BaseModel",
            "from pydantic import BaseModel, ConfigDict, Field, field_validator",
        ).replace(
            "from pydantic import BaseModel, ConfigDict",
            "from pydantic import BaseModel, ConfigDict, Field, field_validator",
        )
    if "ConfigDict" not in src:
        src = src.replace(
            "from pydantic import BaseModel", "from pydantic import BaseModel, ConfigDict"
        )
    if ", Field" not in src and "Field" not in src:
        src = src.replace("from pydantic import BaseModel", "from pydantic import BaseModel, Field")
    return src


def _patch_crud(crud_file: Path, model_name: str, modified: list[str]) -> None:
    """Append bulk_create/update/delete CRUD helpers to ``app/crud/<lower>.py``."""
    _append_if_missing(crud_file, "crud_addition.py.tmpl", "bulk_create", model_name, modified)


def _patch_routes(route_file: Path, model_name: str, modified: list[str]) -> None:
    """Append /bulk endpoints to ``app/api/routes/<lower>.py``."""
    _append_if_missing(route_file, "routes_addition.py.tmpl", "/bulk", model_name, modified)


def _append_if_missing(
    target: Path, template_name: str, sentinel: str, model_name: str, modified: list[str]
) -> None:
    """Append a rendered template to ``target`` when ``sentinel`` is not in the file."""
    if not target.exists():
        return
    src = target.read_text()
    if sentinel in src:
        return
    target.write_text(
        src + render(_HERE, template_name, {"model_name": model_name, "lower": model_name.lower()})
    )
    modified.append(str(target))


def _patch_main(main_file: Path, modified: list[str]) -> None:
    """Wire ``init_idempotency_cache`` into ``app/main.py`` startup — idempotent."""
    src = main_file.read_text()
    if "init_idempotency_cache" in src:
        return
    import_line = "from app.core.idempotency import init_idempotency_cache  # noqa: F401"
    if "from app.core.logging import configure_logging" in src:
        src = src.replace(
            "from app.core.logging import configure_logging",
            f"from app.core.logging import configure_logging\n{import_line}",
        )
    else:
        src = f"{import_line}\n" + src
    init_block = render(_HERE, "main_patch.py.tmpl", {})
    main_file.write_text(src.rstrip("\n") + "\n" + init_block)
    modified.append(str(main_file))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into ``{project}/tests/test_add_bulk_operations_emitted.py``."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_bulk_operations_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_bulk_operations_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
