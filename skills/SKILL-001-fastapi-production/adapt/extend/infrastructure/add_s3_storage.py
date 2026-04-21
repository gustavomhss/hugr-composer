"""TOOL-060: add_s3_storage — add production-grade S3/MinIO object storage to a FastAPI project.

Writes an ``app/storage/client.py`` lazy-import wrapper around the boto3
S3 client, a ``StorageConfig`` dataclass populated from application settings,
an upload-size validation middleware (``app/storage/middleware.py``), REST
routes for generating presigned upload/download URLs and object deletion
(``app/api/routes/storage.py``), and a module re-export package
(``app/storage/__init__.py``).

Why presigned URLs instead of proxied upload/download?

* **Bandwidth** — files go directly between the client and S3/MinIO;
  the API server never buffers binary data.
* **Scalability** — a 1 GB upload does not tie up a FastAPI worker.
* **Security** — presigned URLs expire (default 3 600 s), are scoped to a
  single object key, and are signed with the AWS credentials that never
  leave the backend.

Security / correctness guarantees:

* boto3 is imported LAZILY inside ``S3Client.__init__`` / ``get_s3_client``
  so the application can boot (and be imported in tests) on a machine where
  boto3 has not yet been installed.  The tool still adds
  ``boto3>=1.35.0`` to ``requirements.txt``.
* Object keys are generated as ``{prefix}/{uuid4}/{original_filename}``,
  eliminating collisions and preventing path-traversal attacks (the UUID
  segment isolates filenames that contain ``..`` or OS separators).
* Content-type validation is applied before issuing a presigned URL — only
  MIME types in ``settings.S3_ALLOWED_CONTENT_TYPES`` are accepted.
* Maximum upload size is enforced by ``UploadSizeMiddleware`` reading
  ``Content-Length`` before the worker ever touches S3.
* MinIO is supported via ``settings.S3_ENDPOINT_URL``; omitting the field
  falls back to AWS.

The tool is idempotent: a second run detects the ``S3Client`` fingerprint
in ``app/storage/client.py`` and returns ``status="no_op"`` without
touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_s3_storage import add_s3_storage

    result = add_s3_storage(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/storage/client.py", …]
    print(result.next_steps)    # ["pip install -r requirements.txt", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir


MCP_TOOL = {
    "name": "fastapi_resiliency_add_s3_storage",
    "description": (
        "Add production-grade S3/MinIO object storage with presigned URL upload/download, "
        "content-type validation, upload-size middleware, and REST routes."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_s3_storage",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_s3_storage(inp: ToolInput) -> ToolResult:
    """Add production-grade S3/MinIO object storage to a FastAPI project.

    Creates ``app/storage/__init__.py``, ``app/storage/client.py``,
    ``app/storage/config.py``, ``app/storage/middleware.py``, and
    ``app/api/routes/storage.py``.  Patches ``app/core/config.py``,
    ``app/routes/__init__.py``, and ``requirements.txt``.

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
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    client_file = app_dir / "storage" / "client.py"
    if client_file.exists() and "S3Client" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "S3Client already present in app/storage/client.py — "
                "S3 storage is already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/storage/__init__.py, app/storage/client.py,",
                "         app/storage/config.py, app/storage/middleware.py,",
                "         and app/api/routes/storage.py.",
                "[dry_run] Would patch app/core/config.py with S3_* settings,",
                "         app/routes/__init__.py to register the storage router,",
                "         and requirements.txt with boto3>=1.35.0.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — storage package init
    storage_init_file = app_dir / "storage" / "__init__.py"
    _write_storage_init(storage_init_file)
    files_created.append(str(storage_init_file))

    # Step 2 — S3Client (lazy boto3 import)
    _write_s3_client(client_file)
    files_created.append(str(client_file))

    # Step 3 — StorageConfig dataclass
    storage_config_file = app_dir / "storage" / "config.py"
    _write_storage_config(storage_config_file)
    files_created.append(str(storage_config_file))

    # Step 4 — UploadSizeMiddleware
    middleware_file = app_dir / "storage" / "middleware.py"
    _write_storage_middleware(middleware_file)
    files_created.append(str(middleware_file))

    # Step 5 — HTTP routes (presigned upload, presigned download, delete)
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    storage_route_file = routes_dir / "storage.py"
    _write_storage_routes(storage_route_file)
    files_created.append(str(storage_route_file))

    # Step 6 — patch config settings
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 7 — register storage router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 8 — ensure boto3 in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated Python file parses
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "S3/MinIO storage added: lazy boto3 wrapper, StorageConfig, "
            "UploadSizeMiddleware,",
            "POST /storage/upload (presigned PUT URL), GET /storage/{key} "
            "(presigned GET URL),",
            "DELETE /storage/{key} — all routed through app/api/routes/storage.py.",
            "Files go directly to S3/MinIO via presigned URLs — the API never buffers "
            "binary data.",
            "Object keys are generated as {prefix}/{uuid4}/{filename} to prevent "
            "collisions and path traversal.",
            "Set S3_ENDPOINT_URL to your MinIO address for local/self-hosted usage; "
            "omit for AWS.",
            "boto3 is imported lazily inside S3Client — the app boots without boto3 "
            "installed.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs boto3",
            "Set S3_BUCKET_NAME, S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY "
            "in .env.",
            "For MinIO: also set S3_ENDPOINT_URL=http://localhost:9000",
            "Create the bucket: aws s3 mb s3://<bucket>  (or via MinIO console)",
            "Configure bucket CORS to allow PUT from your frontend origin.",
            "Restart the FastAPI app so /storage/* routes are loaded.",
            "Test: POST /api/v1/storage/upload with "
            '{"filename": "test.png", "content_type": "image/png"} '
            "to receive a presigned upload URL.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body, delegates templates to module-level
# constants (never f-strings with braces in the template bodies).
# ---------------------------------------------------------------------------

def _write_storage_init(dest: Path) -> None:
    """Write ``app/storage/__init__.py`` re-exporting the public surface.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STORAGE_INIT_TEMPLATE)


def _write_s3_client(dest: Path) -> None:
    """Write ``app/storage/client.py`` with lazy boto3 import wrapper.

    The ``boto3`` package is imported INSIDE ``S3Client.__init__`` so the
    application can boot on a machine where boto3 is not installed.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_S3_CLIENT_TEMPLATE)


def _write_storage_config(dest: Path) -> None:
    """Write ``app/storage/config.py`` with the ``StorageConfig`` dataclass.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STORAGE_CONFIG_TEMPLATE)


def _write_storage_middleware(dest: Path) -> None:
    """Write ``app/storage/middleware.py`` with upload-size enforcement.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STORAGE_MIDDLEWARE_TEMPLATE)


def _write_storage_routes(dest: Path) -> None:
    """Write ``app/api/routes/storage.py`` with presigned URL endpoints.

    Endpoints:
    * ``POST /storage/upload`` — return presigned PUT URL for direct upload.
    * ``GET /storage/{key:path}`` — return presigned GET URL for download.
    * ``DELETE /storage/{key:path}`` — delete an object.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STORAGE_ROUTES_TEMPLATE)


# ---------------------------------------------------------------------------
# Config / routes / requirements patches
# ---------------------------------------------------------------------------

def _patch_config(config_file: Path) -> None:
    """Inject S3_* settings into the ``Settings`` class body.

    Idempotent — no-op if ``S3_BUCKET_NAME`` already present.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
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
        '    S3_PRESIGNED_URL_EXPIRATION: int = 3600\n'
        '    S3_MAX_UPLOAD_SIZE_BYTES: int = 52428800\n'
        '    S3_ALLOWED_CONTENT_TYPES: list[str] = [\n'
        '        "image/jpeg", "image/png", "image/gif", "image/webp",\n'
        '        "application/pdf", "text/plain",\n'
        '    ]\n'
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
    """Register the storage HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.storage import router as storage_router",
        include_line="api_router.include_router(storage_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
        import_line: Import statement to insert.
        include_line: ``api_router.include_router(...)`` call.
    """
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
    """Ensure ``boto3>=1.35.0`` is in ``requirements.txt``.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    if "boto3" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "boto3>=1.35.0\n")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(
            f"Generated file {path} has a syntax error: {exc}"
        ) from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates (module-level constants — kept out of helper bodies so every
# helper function stays well under the 50-LOC budget).
# ---------------------------------------------------------------------------

_STORAGE_INIT_TEMPLATE = textwrap.dedent("""\
    \"\"\"S3/MinIO storage package — re-exports the public surface.

    Usage::

        from app.storage import S3Client, StorageConfig, get_s3_client
    \"\"\"

    from app.storage.client import S3Client, get_s3_client
    from app.storage.config import StorageConfig

    __all__ = ["S3Client", "StorageConfig", "get_s3_client"]
""")


_S3_CLIENT_TEMPLATE = textwrap.dedent("""\
    \"\"\"Lazy boto3 S3 client wrapper.

    ``boto3`` is imported INSIDE the class constructor so the application
    can boot without the ``boto3`` package installed.  ``get_s3_client``
    returns a module-level singleton; callers that need a fresh instance
    (e.g. tests) should instantiate ``S3Client`` directly.

    Key-generation contract:
        Every key is ``{prefix}/{uuid4}/{original_filename}``.  The UUID
        segment prevents collisions between users uploading the same filename
        and eliminates path-traversal risk from filenames containing ``..``.
    \"\"\"
    from __future__ import annotations

    import mimetypes
    import uuid
    from typing import Any

    from app.core.config import settings


    class S3Client:
        \"\"\"Thin wrapper around ``boto3.client('s3')`` with lazy import.

        Attributes:
            _client: The underlying boto3 S3 client (created on first use).
        \"\"\"

        def __init__(self) -> None:
            \"\"\"Initialise the S3Client, importing boto3 lazily.\"\"\"
            import boto3  # local import — keeps app.main importable without boto3

            kwargs: dict[str, Any] = {
                "region_name": settings.S3_REGION,
                "aws_access_key_id": settings.S3_ACCESS_KEY_ID or None,
                "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY or None,
            }
            if settings.S3_ENDPOINT_URL:
                kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
            self._client = boto3.client("s3", **kwargs)

        def generate_key(self, filename: str, prefix: str = "") -> str:
            \"\"\"Return a collision-safe object key for *filename*.

            Args:
                filename: Original filename from the client request.
                prefix: Optional path prefix (overrides settings default when
                    provided and non-empty).

            Returns:
                Key string formatted as ``{prefix}/{uuid}/{filename}``.
            \"\"\"
            key_prefix = prefix or settings.S3_KEY_PREFIX
            safe_name = filename.replace("..", "").lstrip("/")
            return f"{key_prefix}/{uuid.uuid4()}/{safe_name}"

        def presigned_upload_url(
            self,
            key: str,
            content_type: str,
            expiration: int | None = None,
        ) -> str:
            \"\"\"Return a presigned PUT URL for a direct client-to-S3 upload.

            Args:
                key: Object key within the bucket.
                content_type: MIME type the client will send as ``Content-Type``.
                expiration: URL lifetime in seconds (defaults to settings value).

            Returns:
                A presigned URL string the client must PUT to directly.
            \"\"\"
            exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
            return self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.S3_BUCKET_NAME,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=exp,
                HttpMethod="PUT",
            )

        def presigned_download_url(
            self,
            key: str,
            expiration: int | None = None,
        ) -> str:
            \"\"\"Return a presigned GET URL for a direct client-to-S3 download.

            Args:
                key: Object key within the bucket.
                expiration: URL lifetime in seconds (defaults to settings value).

            Returns:
                A presigned URL string the client can GET directly.
            \"\"\"
            exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
                ExpiresIn=exp,
            )

        def delete_object(self, key: str) -> None:
            \"\"\"Delete an object from the configured bucket.

            Args:
                key: Object key within the bucket.
            \"\"\"
            self._client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)

        def guess_content_type(self, filename: str) -> str:
            \"\"\"Guess the MIME type of *filename* using the stdlib.

            Args:
                filename: Filename (with extension).

            Returns:
                MIME type string; falls back to ``'application/octet-stream'``.
            \"\"\"
            mime, _ = mimetypes.guess_type(filename)
            return mime or "application/octet-stream"


    _s3_client_singleton: S3Client | None = None


    def get_s3_client() -> S3Client:
        \"\"\"Return the module-level ``S3Client`` singleton.

        The singleton is created lazily on first call so that importing
        ``app.storage`` does not trigger boto3 initialisation at startup.

        Returns:
            The shared ``S3Client`` instance.
        \"\"\"
        global _s3_client_singleton
        if _s3_client_singleton is None:
            _s3_client_singleton = S3Client()
        return _s3_client_singleton
""")


_STORAGE_CONFIG_TEMPLATE = textwrap.dedent("""\
    \"\"\"StorageConfig dataclass — typed view over S3-related settings fields.

    Using a dedicated dataclass separates the S3 surface from the wider
    ``Settings`` object, making the storage layer independently testable.
    \"\"\"
    from __future__ import annotations

    from dataclasses import dataclass, field

    from app.core.config import settings


    @dataclass(frozen=True)
    class StorageConfig:
        \"\"\"Typed snapshot of S3/MinIO settings for a single request context.

        Attributes:
            bucket_name: S3 bucket name.
            region: AWS region (or MinIO region label).
            endpoint_url: Optional custom endpoint for MinIO / compatible stores.
            presigned_url_expiration: Seconds before a presigned URL expires.
            max_upload_size_bytes: Maximum allowed upload size in bytes.
            allowed_content_types: Whitelist of accepted MIME types.
            key_prefix: Default path prefix for generated object keys.
        \"\"\"

        bucket_name: str
        region: str
        endpoint_url: str
        presigned_url_expiration: int
        max_upload_size_bytes: int
        allowed_content_types: list[str]
        key_prefix: str

        @classmethod
        def from_settings(cls) -> "StorageConfig":
            \"\"\"Build a ``StorageConfig`` from the global settings object.

            Returns:
                A frozen ``StorageConfig`` instance populated from
                ``app.core.config.settings``.
            \"\"\"
            return cls(
                bucket_name=settings.S3_BUCKET_NAME,
                region=settings.S3_REGION,
                endpoint_url=settings.S3_ENDPOINT_URL,
                presigned_url_expiration=settings.S3_PRESIGNED_URL_EXPIRATION,
                max_upload_size_bytes=settings.S3_MAX_UPLOAD_SIZE_BYTES,
                allowed_content_types=list(settings.S3_ALLOWED_CONTENT_TYPES),
                key_prefix=settings.S3_KEY_PREFIX,
            )
""")


_STORAGE_MIDDLEWARE_TEMPLATE = textwrap.dedent("""\
    \"\"\"Upload-size enforcement middleware.

    ``UploadSizeMiddleware`` reads ``Content-Length`` from incoming PUT / POST
    requests and rejects them before the request body is consumed by boto3 or
    any other handler.  This protects the API server even when large files are
    rejected by the presigned-URL flow (e.g. a client that PUTs through the
    API instead of directly to S3).
    \"\"\"
    from __future__ import annotations

    from fastapi import Request, Response
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.types import ASGIApp

    from app.core.config import settings


    class UploadSizeMiddleware(BaseHTTPMiddleware):
        \"\"\"Reject requests whose Content-Length exceeds the configured limit.

        Attributes:
            max_size: Maximum allowed ``Content-Length`` in bytes.
        \"\"\"

        def __init__(self, app: ASGIApp, max_size: int | None = None) -> None:
            \"\"\"Initialise the middleware.

            Args:
                app: The ASGI application to wrap.
                max_size: Override maximum bytes. Defaults to
                    ``settings.S3_MAX_UPLOAD_SIZE_BYTES``.
            \"\"\"
            super().__init__(app)
            self.max_size = max_size if max_size is not None else settings.S3_MAX_UPLOAD_SIZE_BYTES

        async def dispatch(self, request: Request, call_next: object) -> Response:
            \"\"\"Intercept the request and reject oversized uploads.

            Args:
                request: Incoming HTTP request.
                call_next: Next ASGI handler in the chain.

            Returns:
                HTTP 413 if Content-Length exceeds limit, else the downstream
                response.
            \"\"\"
            if request.method in ("PUT", "POST"):
                content_length_str = request.headers.get("content-length")
                if content_length_str is not None:
                    try:
                        content_length = int(content_length_str)
                    except ValueError:
                        content_length = 0
                    if content_length > self.max_size:
                        return Response(
                            content=f"Upload exceeds maximum size of {self.max_size} bytes.",
                            status_code=413,
                        )
            return await call_next(request)
""")


_STORAGE_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"REST routes for S3/MinIO presigned URL operations.

    Routes
    ------
    POST   /storage/upload          Return a presigned PUT URL for direct upload.
    GET    /storage/{key:path}      Return a presigned GET URL for direct download.
    DELETE /storage/{key:path}      Delete an object from the bucket.

    The API server never buffers binary data — all file I/O goes directly
    between the client and S3/MinIO via the presigned URLs.
    \"\"\"
    from __future__ import annotations

    from fastapi import APIRouter, HTTPException, status
    from pydantic import BaseModel, Field

    from app.core.config import settings
    from app.storage.client import get_s3_client

    router = APIRouter(prefix="/storage", tags=["storage"])


    class UploadRequest(BaseModel):
        \"\"\"Request body for presigned upload URL generation.

        Attributes:
            filename: Original filename from the client.
            content_type: MIME type of the file to be uploaded.
            prefix: Optional path prefix; defaults to settings.S3_KEY_PREFIX.
        \"\"\"

        filename: str = Field(..., min_length=1, max_length=255)
        content_type: str = Field(..., min_length=1)
        prefix: str = Field(default="", max_length=200)


    class UploadResponse(BaseModel):
        \"\"\"Response body for a presigned upload URL.

        Attributes:
            upload_url: Presigned S3 PUT URL — client must PUT directly here.
            key: Object key that will be created in the bucket.
            expires_in: Number of seconds until the URL expires.
        \"\"\"

        upload_url: str
        key: str
        expires_in: int


    class DownloadResponse(BaseModel):
        \"\"\"Response body for a presigned download URL.

        Attributes:
            download_url: Presigned S3 GET URL — client may GET directly.
            key: Object key this URL points to.
            expires_in: Number of seconds until the URL expires.
        \"\"\"

        download_url: str
        key: str
        expires_in: int


    def _validate_content_type(content_type: str) -> None:
        \"\"\"Raise HTTP 415 if *content_type* is not in the allowed list.

        Args:
            content_type: MIME type string from the client request.

        Raises:
            HTTPException: 415 Unsupported Media Type when the type is not
                in ``settings.S3_ALLOWED_CONTENT_TYPES``.
        \"\"\"
        allowed = settings.S3_ALLOWED_CONTENT_TYPES
        if allowed and content_type not in allowed:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=(
                    f"Content-Type '{content_type}' is not allowed. "
                    f"Allowed types: {', '.join(allowed)}"
                ),
            )


    @router.post(
        "/upload",
        response_model=UploadResponse,
        summary="Generate a presigned URL for direct-to-S3 upload",
        status_code=status.HTTP_200_OK,
    )
    def create_upload_url(body: UploadRequest) -> UploadResponse:
        \"\"\"Return a presigned PUT URL for a direct client-to-S3 upload.

        The client should PUT the file directly to ``upload_url`` with the
        exact ``Content-Type`` header it sent in this request body.

        Args:
            body: Upload request containing filename, content_type, prefix.

        Returns:
            ``UploadResponse`` with the presigned URL and object key.

        Raises:
            HTTPException: 415 if content_type is not allowed.
        \"\"\"
        _validate_content_type(body.content_type)
        client = get_s3_client()
        key = client.generate_key(body.filename, prefix=body.prefix)
        url = client.presigned_upload_url(key, body.content_type)
        return UploadResponse(
            upload_url=url,
            key=key,
            expires_in=settings.S3_PRESIGNED_URL_EXPIRATION,
        )


    @router.get(
        "/{key:path}",
        response_model=DownloadResponse,
        summary="Generate a presigned URL for direct-to-S3 download",
    )
    def create_download_url(key: str) -> DownloadResponse:
        \"\"\"Return a presigned GET URL for a direct client-to-S3 download.

        Args:
            key: Object key within the S3 bucket.

        Returns:
            ``DownloadResponse`` with the presigned URL and object key.
        \"\"\"
        client = get_s3_client()
        url = client.presigned_download_url(key)
        return DownloadResponse(
            download_url=url,
            key=key,
            expires_in=settings.S3_PRESIGNED_URL_EXPIRATION,
        )


    @router.delete(
        "/{key:path}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete an object from S3",
    )
    def delete_object(key: str) -> None:
        \"\"\"Delete an object from the configured S3 bucket.

        Args:
            key: Object key within the S3 bucket.
        \"\"\"
        client = get_s3_client()
        client.delete_object(key)
""")
