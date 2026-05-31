"""TOOL-006: add_data_export — streaming data export for FastAPI/SQLAlchemy.

Generates a memory-bounded streaming export pipeline using SQLAlchemy
server-side cursors and ``StreamingResponse``, covering CSV, NDJSON, XLSX,
and Parquet. Exports above ``EXPORT_ASYNC_THRESHOLD`` rows are promoted to
ARQ background jobs that stream to S3 (or local disk) and email the user
a presigned URL.

Idempotent: a second run detects ``SENSITIVE_COLUMNS`` in
``app/core/export.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

# B0.12 — emitted ``model_registry.py`` keeps registered SQLAlchemy
# model classes inside a ``_ModelRegistry`` instance (class-instance
# singleton, allow-listed by ``r_no_module_state``). The body is
# in-process; under a multi-worker deployment each worker has its own
# copy. ``register_model(...)`` is called declaratively at app-import
# time so every worker (including the ARQ background worker that runs
# the export jobs) populates the registry identically at boot. This
# flag + the ``single-process`` ``warnings=`` entry below disclose the
# trade-off explicitly. Swap the registry body for a Redis/DB-backed
# store if dynamic runtime registration across workers is ever
# required (public surface unchanged).
_SINGLE_PROCESS_OK: bool = True

MCP_TOOL = {
    "name": "fastapi_data_add_data_export",
    "description": "Add CSV/XLSX data export endpoints for all major resources.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_export",
}

_SKIP_MODELS: frozenset[str] = frozenset({"base", "user", "mixins", "__init__", "tenant"})


def add_data_export(inp: ToolInput) -> ToolResult:
    """Add streaming data export capability to a FastAPI project."""
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

    from adapt.contracts.prerequisites import Prereq, ensure_prerequisites

    prereq_errors, scaffolded = ensure_prerequisites(
        inp.project_dir,
        Prereq.BASE_MODEL,
        Prereq.CONFIG_SETTINGS,
        Prereq.ROUTES_INIT,
        Prereq.ALEMBIC_VERSIONS,
        Prereq.REQUIREMENTS_TXT,
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
    export_core = app_dir / "core" / "export.py"

    if export_core.exists() and "SENSITIVE_COLUMNS" in export_core.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "app/core/export.py with SENSITIVE_COLUMNS already present — export already enabled."
            ],
            execution_time_ms=_ms(start),
        )

    model_pairs = _discover_models(app_dir)
    if not model_pairs:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_ms(start),
        )
    model_names = [pascal for _stem, pascal in model_pairs]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add data export for: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Steps 1-5 — core modules (export utilities, ARQ dispatcher, progress, storage, registry).
    _emit(export_core, "export.py.tmpl", files_created)
    _emit(app_dir / "core" / "export_jobs.py", "export_jobs.py.tmpl", files_created)
    _emit(app_dir / "core" / "export_progress.py", "export_progress.py.tmpl", files_created)
    storage_file = app_dir / "core" / "storage.py"
    if not storage_file.exists():
        _emit(storage_file, "storage.py.tmpl", files_created)
    registry_file = app_dir / "core" / "model_registry.py"
    if not registry_file.exists():
        _emit(registry_file, "model_registry.py.tmpl", files_created)

    # Step 6 — ARQ background worker package + run_export entrypoint.
    jobs_dir = app_dir / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    jobs_init = jobs_dir / "__init__.py"
    if not jobs_init.exists():
        render_to(_HERE, "jobs_init.py.tmpl", dest=jobs_init, substitutions={})
        files_created.append(str(jobs_init))
    _emit(jobs_dir / "export.py", "arq_worker.py.tmpl", files_created)

    # Step 7 — patch routes per model with /export endpoint.
    for stem, model_name in model_pairs:
        route_file = app_dir / "api" / "routes" / f"{stem}.py"
        if not route_file.exists():
            continue
        src = route_file.read_text()
        if "/export" in src or "StreamingResponse" in src:
            continue
        additions = render(
            _HERE,
            "routes_addition.py.tmpl",
            {"model_name": model_name, "lower": stem},
        )
        route_file.write_text(src + additions)
        files_modified.append(str(route_file))

    # Step 8 — Alembic migration for export_jobs tracking table.
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "0006_add_export_jobs.py"
        if not mig_file.exists():
            render_to(
                _HERE,
                "migration.py.tmpl",
                dest=mig_file,
                substitutions={"down_rev": down_rev},
            )
            files_created.append(str(mig_file))

    # Step 9 — requirements.txt addenda.
    req_file = project / "requirements.txt"
    if req_file.exists():
        req_src = req_file.read_text()
        req_adds = []
        if "pyarrow" not in req_src:
            req_adds.append("pyarrow>=17.0.0")
        if "xlsxwriter" not in req_src:
            req_adds.append("xlsxwriter>=3.2.0")
        if "redis" not in req_src:
            req_adds.append("redis[hiredis]>=5.0.0")
        if req_adds:
            req_file.write_text(req_src.rstrip("\n") + "\n" + "\n".join(req_adds) + "\n")
            files_modified.append(str(req_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Data export enabled for: {', '.join(model_names or [])}",
            "Streaming export uses server-side cursors — never loads full dataset in RAM.",
            "Exports above EXPORT_ASYNC_THRESHOLD rows are dispatched as ARQ background jobs.",
            "SENSITIVE_COLUMNS (hashed_password, api_key, etc.) always excluded.",
        ],
        warnings=[
            # B0.12 disclosure — paired with _SINGLE_PROCESS_OK = True
            # above. The emitted model_registry's _ModelRegistry is
            # in-process; under multi-worker (gunicorn -w N / uvicorn
            # --workers) each worker has its own copy. register_model
            # is called declaratively at import time on every worker
            # (including the ARQ worker process that runs the export
            # jobs), so the registry is fully populated identically
            # on every worker. Swap the registry body for a Redis/DB
            # store if dynamic runtime registration across workers is
            # required.
            "Export model registry is single-process (in-memory). "
            "Multi-worker deployments: every worker (including the ARQ "
            "background worker) re-runs register_model declaratively "
            "at import time, so registry contents stay consistent. "
            "For runtime cross-worker dynamic registration swap "
            "_ModelRegistry for a Redis/DB-backed store.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set EXPORT_ASYNC_THRESHOLD in your .env (default: 10000 rows).",
            "Set STORAGE_BACKEND=s3 and AWS_S3_BUCKET for async export storage.",
            "Register run_export in your ARQ WorkerSettings.functions list.",
            "Restart the application.",
        ],
        execution_time_ms=_ms(start),
    )


_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs whose file stem matches a routable model."""
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    pairs: list[tuple[str, str]] = []
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
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
        for real_name in (c for c in base_subclasses if c.lower() == stem):
            pairs.append((stem, real_name))
    return pairs


def _emit(dest: Path, template_name: str, created: list[str]) -> None:
    """Render a placeholder-free template to ``dest`` and append to created list."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, template_name, dest=dest, substitutions={})
    created.append(str(dest))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into ``{project}/tests/test_add_data_export_emitted.py``."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_data_export_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_data_export_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
