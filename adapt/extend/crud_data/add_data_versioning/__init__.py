"""TOOL-078: add_data_versioning — draft/published/archived lifecycle via templates.

Generates a ContentVersion model + VersioningService (create_draft, publish,
archive, get_history, diff) + Pydantic schemas + CRUD + REST endpoints. All
emitted code lives in templates/*.py.tmpl. VERSIONING_MAX_DRAFTS bounds
concurrent drafts per content item. History is append-only.
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

MCP_TOOL = {
    "name": "fastapi_data_add_data_versioning",
    "description": "Add draft/published/archived lifecycle with diff to any content type.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_versioning",
    "imports_primitives": [],
    "imports_adapters": [],

}


def add_data_versioning(inp: ToolInput) -> ToolResult:
    """Add content versioning (draft/published/archived) to a FastAPI project."""
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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded or [])
    app_dir = project / "app"

    version_model = app_dir / "models" / "content_version.py"
    if version_model.exists() and "ContentVersion" in version_model.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "ContentVersion model already present — data versioning is already enabled, skipped."
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add content versioning (ContentVersion, VersioningService).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    files_created.append(
        str(_render_to(app_dir / "versioning" / "__init__.py", "versioning_init.py.tmpl"))
    )
    files_created.append(
        str(_render_to(app_dir / "versioning" / "service.py", "versioning_service.py.tmpl"))
    )
    files_created.append(str(_render_to(version_model, "content_version_model.py.tmpl")))
    _patch_models_init(app_dir / "models" / "__init__.py", [("content_version", "ContentVersion")])
    files_created.append(
        str(_render_to(app_dir / "schemas" / "version.py", "version_schema.py.tmpl"))
    )
    files_created.append(str(_render_to(app_dir / "crud" / "version.py", "version_crud.py.tmpl")))
    files_created.append(
        str(_render_to(app_dir / "api" / "routes" / "versions.py", "version_routes.py.tmpl"))
    )

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        rev_id = "add_content_versions"
        down_rev = find_migration_head(versions_dir) or "0001_initial"
        files_created.append(
            str(
                render_to(
                    _HERE,
                    "migration.py.tmpl",
                    dest=versions_dir / f"{rev_id}.py",
                    substitutions={"rev_id": rev_id, "down_rev": down_rev},
                )
            )
        )

    _emit_project_test(project, files_created)

    for path_str in files_created:
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

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "ContentVersion model created (content_id, version_number, status, data_json, "
            "published_at, author_id).",
            "VersioningService: create_draft, publish, archive, get_history, diff.",
            "Lifecycle: pending → draft → published → archived.",
            "Diff uses DeepDiff-style JSON field comparison (no external dep).",
            "Config: VERSIONING_MAX_DRAFTS (default 10) limits concurrent drafts per content.",
            "Routes: draft, publish, archive, history, diff — under /versions/{content_type}/{id}.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set VERSIONING_MAX_DRAFTS in your .env to change concurrent draft limit.",
            "Pass author_id (user UUID) to VersioningService calls.",
            "Restart the application.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _render_to(dest: Path, template_name: str) -> Path:
    """Render a parameter-less template to *dest*."""
    return render_to(_HERE, template_name, dest=dest, substitutions={})


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
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


def _patch_routes_init(routes_init: Path) -> None:
    src = routes_init.read_text()
    if "versions_router" in src:
        return
    addition = render(_HERE, "routes_init_addition.py.tmpl", {})
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def _patch_config(config_file: Path) -> None:
    from adapt.contracts.config_patcher import patch_settings_fields

    patch_settings_fields(
        config_file,
        fields=[("VERSIONING_MAX_DRAFTS", "VERSIONING_MAX_DRAFTS: int = 10")],
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_data_versioning_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_data_versioning_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return max(1, int((time.monotonic() - start) * 1000))
