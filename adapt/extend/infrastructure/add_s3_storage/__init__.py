"""TOOL-060: add_s3_storage — add production-grade S3/MinIO object storage to a FastAPI project.

Writes an ``app/storage/client.py`` lazy-import wrapper around the boto3
S3 client, a ``StorageConfig`` dataclass populated from application settings,
an upload-size validation middleware (``app/storage/middleware.py``), REST
routes for generating presigned upload/download URLs and object deletion
(``app/api/routes/storage.py``), and a module re-export package
(``app/storage/__init__.py``).

The tool is idempotent: a second run detects the ``S3Client`` fingerprint
in ``app/storage/client.py`` and returns ``status="no_op"``.

Warnings:
    - boto3 is imported LAZILY inside S3Client.__init__ so the app boots without it.
    - Server-side encryption (SSE) is NOT enforced; configure bucket-level SSE separately.
    - The tool does NOT stage real S3 payloads; presigned URLs require a live S3/MinIO.
"""

from __future__ import annotations

import time
from pathlib import Path

from adapt._base import render_to
from adapt.contracts import ToolInput, ToolResult, validate_project_dir

_HERE = Path(__file__).parent

MCP_TOOL = {
    "name": "fastapi_resiliency_add_s3_storage",
    "description": (
        "Add production-grade S3/MinIO object storage with presigned URL upload/download, "
        "content-type validation, upload-size middleware, and REST routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_s3_storage",
}


def add_s3_storage(inp: ToolInput) -> ToolResult:
    """Add production-grade S3/MinIO object storage to a FastAPI project.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_ms(start))

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
            notes=[
                "These prerequisites cannot be auto-created.",
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    client_file = app_dir / "storage" / "client.py"
    if client_file.exists() and "S3Client" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "S3Client already present in app/storage/client.py — S3 storage is already installed, skipped."
            ],
            execution_time_ms=_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/storage/__init__.py, app/storage/client.py,",
                "         app/storage/config.py, app/storage/middleware.py,",
                "         and app/api/routes/storage.py.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_ms(start),
        )

    files_modified: list[str] = []

    storage_init_file = app_dir / "storage" / "__init__.py"
    render_to(_HERE, "storage_init.py.tmpl", dest=storage_init_file, substitutions={})
    files_created.append(str(storage_init_file))

    render_to(_HERE, "client.py.tmpl", dest=client_file, substitutions={})
    files_created.append(str(client_file))

    storage_config_file = app_dir / "storage" / "config.py"
    render_to(_HERE, "config.py.tmpl", dest=storage_config_file, substitutions={})
    files_created.append(str(storage_config_file))

    middleware_file = app_dir / "storage" / "middleware.py"
    render_to(_HERE, "middleware.py.tmpl", dest=middleware_file, substitutions={})
    files_created.append(str(middleware_file))

    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    storage_route_file = routes_dir / "storage.py"
    render_to(_HERE, "routes.py.tmpl", dest=storage_route_file, substitutions={})
    files_created.append(str(storage_route_file))

    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    _emit_project_test(project, files_created)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "S3/MinIO storage added: lazy boto3 wrapper, StorageConfig, UploadSizeMiddleware,",
            "POST /storage/upload (presigned PUT URL), GET /storage/{key} (presigned GET URL),",
            "DELETE /storage/{key} — all routed through app/api/routes/storage.py.",
            "All three routes require an authenticated CurrentUser and are PREFIX-SCOPED to",
            "users/{current_user.id}/ — cross-user GET/DELETE is rejected with 403",
            "(closes R6-S6-F1 / F5 / F6 / F7).",
            "Files go directly to S3/MinIO via presigned URLs — the API never buffers binary data.",
            "Object keys are generated as users/{user_id}/{uuid4}/{filename} to prevent collisions",
            "and enforce per-user namespace isolation.",
            "boto3 is imported lazily inside S3Client — the app boots without boto3 installed.",
            "WARNING: server-side encryption (SSE) is NOT enforced; configure bucket-level SSE separately.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs boto3",
            "Set S3_BUCKET_NAME, S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY in .env.",
            "For MinIO: also set S3_ENDPOINT_URL=http://localhost:9000",
            "Create the bucket: aws s3 mb s3://<bucket>  (or via MinIO console)",
            "Configure bucket CORS to allow PUT from your frontend origin.",
        ],
        execution_time_ms=_ms(start),
    )


def _emit_project_test(project: Path, created: list[str]) -> None:
    (project / "tests").mkdir(parents=True, exist_ok=True)
    emitted = project / "tests" / "test_add_s3_storage_emitted.py"
    if emitted.exists():
        return
    render_to(_HERE, "test_add_s3_storage_emitted.py.tmpl", dest=emitted, substitutions={})
    created.append(str(emitted))


def _patch_config(config_file: Path) -> None:
    """Inject S3_* settings into the ``Settings`` class body."""
    src = config_file.read_text()
    if "S3_BUCKET_NAME" in src:
        return

    block = (
        "\n"
        "    # --- S3/MinIO object storage — added by add_s3_storage tool ---\n"
        '    S3_BUCKET_NAME: str = "my-app-bucket"\n'
        '    S3_REGION: str = "us-east-1"\n'
        '    S3_ENDPOINT_URL: str = ""\n'
        '    S3_ACCESS_KEY_ID: str = ""\n'
        '    S3_SECRET_ACCESS_KEY: str = ""\n'
        "    S3_PRESIGNED_URL_EXPIRATION: int = 3600\n"
        "    S3_MAX_UPLOAD_SIZE_BYTES: int = 52428800\n"
        "    S3_ALLOWED_CONTENT_TYPES: list[str] = [\n"
        '        "image/jpeg", "image/png", "image/gif", "image/webp",\n'
        '        "application/pdf", "text/plain",\n'
        "    ]\n"
        '    S3_KEY_PREFIX: str = "uploads"\n'
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(settings_line, block.lstrip("\n") + "\n\n" + settings_line)
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the storage HTTP router in ``app/routes/__init__.py``."""
    _register_router(
        routes_init,
        import_line="from app.api.routes.storage import router as storage_router",
        include_line="api_router.include_router(storage_router)",
    )


def _register_router(routes_init: Path, *, import_line: str, include_line: str) -> None:
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


def _patch_requirements(requirements_file: Path) -> None:
    src = requirements_file.read_text()
    if "boto3" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "boto3>=1.35.0\n")


def _ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
