"""TOOL-003: add_file_upload — production file upload via externalized templates.

Generates FileMetadata + StorageBackend (Local/S3) + magic-byte MIME validator
+ presigned URL helpers + per-user quota + S3 multipart helper + orphan cleanup
+ CRUD/schemas/routes + Alembic migration. All emitted code lives in
templates/*.py.tmpl. LocalStorage.save streams via CHUNK_SIZE — no full-file
buffering. FileMetadataPublic intentionally excludes stored_key and tenant_id.
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
    "name": "fastapi_data_add_file_upload",
    "description": "Add file upload support (multipart/form-data) with S3-compatible storage backend.",
    "tags": ["extend", "crud_data"],
    "entry": "add_file_upload",
}


def add_file_upload(inp: ToolInput) -> ToolResult:
    """Add a production-grade file upload system to a FastAPI project."""
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
        Prereq.REQUIREMENTS_TXT,
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
    model_file = app_dir / "models" / "file.py"
    if model_file.exists() and "FileMetadata" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["FileMetadata already present — file upload already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create FileMetadata model, storage backend, validator,",
                "[dry_run] presigned URLs, quota enforcer, multipart helper, cleanup task,",
                "[dry_run] CRUD, routes, schemas, migration, and requirements additions.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    files_created.append(str(_render(model_file, "file_model.py.tmpl")))
    _patch_models_init(app_dir / "models" / "__init__.py", [("file", "FileMetadata")])
    files_created.append(str(_render(app_dir / "core" / "storage.py", "storage.py.tmpl")))
    files_created.append(
        str(_render(app_dir / "core" / "file_validator.py", "file_validator.py.tmpl"))
    )
    files_created.append(
        str(_render(app_dir / "core" / "presigned_urls.py", "presigned_urls.py.tmpl"))
    )
    files_created.append(str(_render(app_dir / "core" / "upload_quota.py", "upload_quota.py.tmpl")))
    files_created.append(
        str(_render(app_dir / "core" / "multipart_upload.py", "multipart_upload.py.tmpl"))
    )

    tasks_dir = app_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_init = tasks_dir / "__init__.py"
    if not tasks_init.exists():
        tasks_init.write_text('"""Task modules."""\n')
        files_created.append(str(tasks_init))
    files_created.append(str(_render(tasks_dir / "cleanup_orphans.py", "cleanup_orphans.py.tmpl")))

    files_created.append(str(_render(app_dir / "crud" / "file.py", "file_crud.py.tmpl")))
    files_created.append(str(_render(app_dir / "schemas" / "file.py", "file_schemas.py.tmpl")))
    files_created.append(
        str(_render(app_dir / "api" / "routes" / "files.py", "file_routes.py.tmpl"))
    )

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        rev_id = "create_files_table"
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
            "File upload system enabled: FileMetadata model, LocalStorage + S3Storage.",
            "MIME validation uses magic bytes — never trusts Content-Type header or extension.",
            "Files are never proxied through the server on the S3 path (presigned URL workflow).",
            "LocalStorage uses atomic temp-file rename: no partial writes visible to readers.",
            "Per-user quota enforced with Redis advisory lock to prevent race conditions.",
            "FileMetadataPublic does NOT expose stored_key or tenant_id.",
        ],
        next_steps=[
            "alembic upgrade head",
            "pip install python-magic>=0.4.27 boto3>=1.34.0 redis>=5.0.0",
            "Set STORAGE_BACKEND, UPLOAD_DIR / S3_BUCKET, MAX_UPLOAD_SIZE_MB in .env",
            "Register cleanup_orphaned_uploads in your ARQ / Celery scheduler.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


def _render(dest: Path, name: str) -> Path:
    return render_to(_HERE, name, dest=dest, substitutions={})


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


def _patch_api_main(routes_init: Path) -> None:
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.files import router as files_router",
        include_line="api_router.include_router(files_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path, *, import_line: str, include_line: str
) -> None:
    src = routes_init.read_text()
    if import_line in src:
        return

    lines = src.splitlines()
    last_app_import_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("from app."):
            last_app_import_idx = idx
    if last_app_import_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_app_import_idx = idx - 1
                break
    lines.insert(last_app_import_idx + 1, import_line)

    last_include_idx = -1
    for idx, line in enumerate(lines):
        if line.startswith("api_router.include_router"):
            last_include_idx = idx
    if last_include_idx == -1:
        for idx, line in enumerate(lines):
            if "api_router" in line and "APIRouter()" in line:
                last_include_idx = idx
                break
    lines.insert(last_include_idx + 1, include_line)
    routes_init.write_text("\n".join(lines) + ("\n" if src.endswith("\n") else ""))


def _patch_config(config_file: Path) -> None:
    src = config_file.read_text()
    if "STORAGE_BACKEND" in src:
        return
    additions = render(_HERE, "config_additions.py.tmpl", {})
    config_file.write_text(src + additions)


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    lines_to_add = []
    if "python-magic" not in src:
        lines_to_add.append("python-magic>=0.4.27")
    if "boto3" not in src:
        lines_to_add.append("boto3>=1.34.0")
    if "redis" not in src:
        lines_to_add.append("redis>=5.0.0")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_file_upload_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_file_upload_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
