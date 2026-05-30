"""TOOL-077: add_data_import — CSV/Excel upload with async processing.

Generates a production-grade data import pipeline: upload endpoint, async row
validation, batch processing, ImportJob model tracking status/progress/errors,
and a configurable RowValidator. Large files are processed in background tasks
so the upload endpoint returns immediately with a job ID; per-row errors are
collected and exposed via a dedicated error-report endpoint.

Idempotent: a second run detects ``ImportJob`` in
``app/models/import_job.py`` and returns ``status="no_op"``.
"""

from __future__ import annotations

import ast
import time
from pathlib import Path

from adapt._base import render, render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_data_add_data_import",
    "description": "Add CSV/Excel upload with async processing, validation and error reporting.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_import",
}


def add_data_import(inp: ToolInput) -> ToolResult:
    """Add CSV/Excel data import capability to a FastAPI project."""
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
    import_model = app_dir / "models" / "import_job.py"

    if import_model.exists() and "ImportJob" in import_model.read_text():
        return ToolResult(
            status="no_op",
            notes=["ImportJob model already present — data import is already enabled."],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add data import pipeline (ImportJob model, processor, validator).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    # Steps 1-3 — package, validators, processor.
    _emit(app_dir / "imports" / "__init__.py", "imports_init.py.tmpl", files_created)
    _emit(app_dir / "imports" / "validators.py", "validators.py.tmpl", files_created)
    _emit(app_dir / "imports" / "processor.py", "processor.py.tmpl", files_created)

    # Step 4 — ImportJob model + registry patch.
    _emit(import_model, "import_job_model.py.tmpl", files_created)
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("import_job", "ImportJob")],
    )

    # Steps 5-7 — schema, CRUD, routes.
    _emit(app_dir / "schemas" / "import_job.py", "import_job_schema.py.tmpl", files_created)
    _emit(app_dir / "crud" / "import_job.py", "import_job_crud.py.tmpl", files_created)
    _emit(app_dir / "api" / "routes" / "imports.py", "import_routes.py.tmpl", files_created)

    # Step 8 — register router in app/routes/__init__.py.
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init, files_modified)

    # Step 9 — patch config.py with import settings.
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, files_modified)

    # Step 10 — Alembic migration.
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        mig_file = versions_dir / "add_import_jobs.py"
        if not mig_file.exists():
            render_to(
                _HERE,
                "migration.py.tmpl",
                dest=mig_file,
                substitutions={"down_rev": down_rev},
            )
            files_created.append(str(mig_file))

    # ast.parse safety net for every emitted .py file.
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py" and p.is_file():
            try:
                ast.parse(p.read_text())
            except SyntaxError as exc:
                return ToolResult(
                    status="error",
                    error=f"Generated file has syntax error: {p}: {exc}",
                    execution_time_ms=_ms(start),
                )

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "ImportJob model created (tracks status, progress, failed rows, error_report_url).",
            "ImportProcessor supports CSV and Excel (lazy openpyxl import).",
            "RowValidator supports configurable required-fields and type rules.",
            "Routes: POST /imports/upload, GET /imports/{id}/status, GET /imports/{id}/errors.",
            "Config: IMPORT_MAX_FILE_SIZE_MB (default 50), IMPORT_BATCH_SIZE (default 500).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set IMPORT_MAX_FILE_SIZE_MB and IMPORT_BATCH_SIZE in your .env as needed.",
            "Call process_import_job() from your background task worker after upload.",
            "Restart the application.",
        ],
        execution_time_ms=_ms(start),
    )


_PREREQ_NOTES = [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
]


def _emit(dest: Path, template_name: str, created: list[str]) -> None:
    """Render placeholder-free template to ``dest`` and append to created list."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    render_to(_HERE, template_name, dest=dest, substitutions={})
    created.append(str(dest))


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
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


def _patch_routes_init(routes_init: Path, modified: list[str]) -> None:
    """Register imports router in ``app/routes/__init__.py``."""
    src = routes_init.read_text()
    if "imports_router" in src:
        return
    addition = render(_HERE, "routes_init_patch.py.tmpl", {})
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)
    modified.append(str(routes_init))


def _patch_config(config_file: Path, modified: list[str]) -> None:
    """Inject IMPORT_* settings into ``app/core/config.py`` via the shared patcher."""
    from adapt.contracts.config_patcher import patch_settings_fields

    before = config_file.read_text()
    patch_settings_fields(
        config_file,
        fields=[
            ("IMPORT_MAX_FILE_SIZE_MB", "IMPORT_MAX_FILE_SIZE_MB: int = 50"),
            ("IMPORT_BATCH_SIZE", "IMPORT_BATCH_SIZE: int = 500"),
        ],
    )
    if config_file.read_text() != before:
        modified.append(str(config_file))


def _emit_project_test(project: Path, created: list[str]) -> None:
    """Render emitted test into ``{project}/tests/test_add_data_import_emitted.py``."""
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_data_import_emitted.py"
    if emitted.exists():
        return
    render_to(
        _HERE,
        "test_add_data_import_emitted.py.tmpl",
        dest=emitted,
        substitutions={},
    )
    created.append(str(emitted))


def _ms(start: float) -> int:
    return max(1, int((time.monotonic() - start) * 1000))
