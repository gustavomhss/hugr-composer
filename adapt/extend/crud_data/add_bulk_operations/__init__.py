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
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.tool_result import _elapsed_ms
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

DEFAULT_MAX_BATCH: int = 1000

MCP_TOOL = {
    "name": "fastapi_data_add_bulk_operations",
    "description": "Add bulk create/update/delete endpoints for all models.",
    "tags": ["extend", "crud_data"],
    "entry": "add_bulk_operations",
    "imports_primitives": [],
    "imports_adapters": [],

}

_SKIP_MODELS: frozenset[str] = frozenset({"base", "user", "mixins", "__init__", "tenant"})


def add_bulk_operations(inp: ToolInput) -> ToolResult:
    """Add bulk create/update/delete endpoints to a FastAPI project."""
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
            notes=_PREREQ_NOTES,
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"
    idempotency_file = app_dir / "core" / "idempotency.py"

    if idempotency_file.exists() and "IdempotencyCache" in idempotency_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["IdempotencyCache already present — bulk operations already enabled."],
            execution_time_ms=_elapsed_ms(start),
        )

    model_names = _discover_models(app_dir)
    if not model_names:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add bulk operations for: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
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
        execution_time_ms=_elapsed_ms(start),
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
    """Wire ``init_idempotency_cache`` + ``close_idempotency_cache`` into
    ``app/main.py``'s ``async def lifespan(...)`` — idempotent.

    Mirrors the ``add_arq_worker._patch_main`` pattern (insert before the
    ``yield`` for startup, after for shutdown). Closes CONTRACT §B0.15
    (triage R5-O2-D12 + R6-O2-O2-2): the previous EOF-append shape built
    the Redis client at module import time, with no startup gate and no
    shutdown.

    When ``async def lifespan(...)`` is NOT present (a non-standard
    main.py shape), the patcher falls back to the historical EOF-append
    behaviour so the tool still completes; ``# pragma: B0.15: ...`` is
    attached so the contract rule allows the literal fallback line.
    """
    src = main_file.read_text()
    if "init_idempotency_cache" in src:
        return

    import_line = (
        "from app.core.idempotency import close_idempotency_cache, init_idempotency_cache"
    )
    lines = src.splitlines()

    # 1. Insert the import — prefer right after the last `from app.` line
    #    (matches the add_arq_worker pattern), else after the configure_logging
    #    import (legacy anchor), else at the very top.
    last_from_app = max(
        (i for i, ln in enumerate(lines) if ln.startswith("from app.")),
        default=-1,
    )
    if last_from_app != -1:
        lines.insert(last_from_app + 1, import_line)
    else:
        logging_anchor = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.strip() == "from app.core.logging import configure_logging"
            ),
            -1,
        )
        if logging_anchor != -1:
            lines.insert(logging_anchor + 1, import_line)
        else:
            lines.insert(0, import_line)

    # 2. Splice the startup + shutdown calls into the `lifespan` body.
    yield_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "yield"), -1)
    if yield_idx != -1:
        raw = lines[yield_idx]
        indent = raw[: len(raw) - len(raw.lstrip())]
        startup_lines = [
            f"{indent}# --- add_bulk_operations: idempotency cache startup ---",
            f'{indent}_idem_redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")',
            f"{indent}init_idempotency_cache(_idem_redis_url)",
        ]
        # `os` is needed in the lifespan body for REDIS_URL lookup; alias to
        # `_os` so we don't collide with any existing `os` import.
        os_import = "import os as _os  # add_bulk_operations: REDIS_URL lookup"
        if os_import not in src and "import os as _os" not in "\n".join(lines):
            # Insert near the other stdlib imports — top of file is safest.
            insert_at = 0
            for i, ln in enumerate(lines[:30]):
                if ln.startswith(("import ", "from ")) and "app." not in ln:
                    insert_at = i + 1
            lines.insert(insert_at, os_import)
            yield_idx += 1  # shift after inserting at top
        # Splice startup BEFORE yield, shutdown AFTER.
        for offset, ln in enumerate(startup_lines):
            lines.insert(yield_idx + offset, ln)
        shutdown_at = yield_idx + len(startup_lines) + 1  # after `yield`
        shutdown_lines = [
            f"{indent}# --- add_bulk_operations: idempotency cache shutdown ---",
            f"{indent}await close_idempotency_cache()",
        ]
        for offset, ln in enumerate(shutdown_lines):
            lines.insert(shutdown_at + offset, ln)
        main_file.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))
    else:
        # Fallback for non-standard main.py shapes — keep the legacy
        # EOF-append behaviour but pragma it so B0.15 allows the line.
        fallback = (
            "\n\n"
            "# Idempotency cache — added by add_bulk_operations tool\n"
            "# (no `async def lifespan(...)` found in this main.py — see "
            "CONTRACT §B0.15 fallback note in `_patch_main`).\n"
            "import os as _os\n"
            '_idem_redis_url = _os.getenv("REDIS_URL", "redis://localhost:6379/0")\n'
            "init_idempotency_cache(_idem_redis_url)"
            "  # pragma: B0.15: non-standard main.py has no `lifespan`; "
            "fallback retains legacy module-top init\n"
        )
        main_file.write_text(
            "\n".join(lines).rstrip("\n") + fallback
        )
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


