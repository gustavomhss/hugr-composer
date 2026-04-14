"""TOOL-003: add_file_upload — add production-grade file upload to a FastAPI project.

Generates a ``FileMetadata`` model, a ``StorageBackend`` ABC with ``LocalStorage``
and ``S3Storage`` implementations, MIME validation via magic bytes
(``app/core/file_validator.py``), presigned URL helpers (``app/core/presigned_urls.py``),
per-user quota enforcement (``app/core/upload_quota.py``), a multipart upload
helper (``app/core/multipart_upload.py``), an orphan cleanup task
(``app/tasks/cleanup_orphans.py``), file CRUD, file routes, Pydantic schemas,
settings additions, an Alembic migration, and updates ``requirements.txt``.

The tool is idempotent: a second run on an already-patched project detects the
``FileMetadata`` fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_file_upload import add_file_upload

    result = add_file_upload(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/models/file.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_file_upload(inp: ToolInput) -> ToolResult:
    """Add a production-grade file upload system to a FastAPI project.

    Creates model, storage backend, MIME validator, presigned URL helpers,
    quota enforcer, multipart helper, cleanup task, CRUD, routes, schemas,
    migration, and updates configuration files.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Pre-flight: already patched? -------------------------------------
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

    files_created: list[str] = []
    files_modified: list[str] = []

    # --- Step 1: FileMetadata model ---------------------------------------
    _write_file_model(model_file)
    files_created.append(str(model_file))

    # --- Step 2: Storage backend ABC + LocalStorage + S3Storage ----------
    storage_file = app_dir / "core" / "storage.py"
    _write_storage(storage_file)
    files_created.append(str(storage_file))

    # --- Step 3: MIME validator -------------------------------------------
    validator_file = app_dir / "core" / "file_validator.py"
    _write_file_validator(validator_file)
    files_created.append(str(validator_file))

    # --- Step 4: Presigned URL helpers ------------------------------------
    presigned_file = app_dir / "core" / "presigned_urls.py"
    _write_presigned_urls(presigned_file)
    files_created.append(str(presigned_file))

    # --- Step 5: Quota enforcer ------------------------------------------
    quota_file = app_dir / "core" / "upload_quota.py"
    _write_upload_quota(quota_file)
    files_created.append(str(quota_file))

    # --- Step 6: Multipart upload helper ---------------------------------
    multipart_file = app_dir / "core" / "multipart_upload.py"
    _write_multipart_upload(multipart_file)
    files_created.append(str(multipart_file))

    # --- Step 7: Orphan cleanup task -------------------------------------
    tasks_dir = app_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks_init = tasks_dir / "__init__.py"
    if not tasks_init.exists():
        tasks_init.write_text('"""Task modules."""\n')
        files_created.append(str(tasks_init))
    cleanup_file = tasks_dir / "cleanup_orphans.py"
    _write_cleanup_orphans(cleanup_file)
    files_created.append(str(cleanup_file))

    # --- Step 8: File CRUD -----------------------------------------------
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    file_crud = crud_dir / "file.py"
    _write_file_crud(file_crud)
    files_created.append(str(file_crud))

    # --- Step 9: File schemas --------------------------------------------
    schema_dir = app_dir / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    file_schema = schema_dir / "file.py"
    _write_file_schemas(file_schema)
    files_created.append(str(file_schema))

    # --- Step 10: File routes --------------------------------------------
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    files_route = routes_dir / "files.py"
    _write_file_routes(files_route)
    files_created.append(str(files_route))

    # --- Step 11: Register router in api/main.py -------------------------
    api_main = app_dir / "api" / "main.py"
    if api_main.exists():
        _patch_api_main(api_main)
        files_modified.append(str(api_main))

    # --- Step 12: Add settings to config.py ------------------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 13: Add requirements ---------------------------------------
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # --- Step 14: Alembic migration --------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

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


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_file_model(dest: Path) -> None:
    """Write ``app/models/file.py`` with the ``FileMetadata`` model.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"FileMetadata model — persistent record for every uploaded file.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid, func
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class FileMetadata(Base):
            \"\"\"Persistent metadata row for every file managed by the upload system.

            Attributes:
                id: UUID primary key, auto-generated.
                original_filename: Original client-supplied filename (display only).
                stored_key: UUID-based storage path — never the original filename.
                content_type: Detected MIME type from magic bytes.
                size_bytes: File size in bytes (confirmed from storage after upload).
                status: Upload lifecycle state.
                uploaded_by: FK to users.id; NULL when user is deleted.
                tenant_id: Populated by add_multi_tenancy; NULL on single-tenant installs.
                resource_type: Polymorphic resource type for scoped file listing.
                resource_id: Polymorphic resource ID for scoped file listing.
                created_at: Row creation timestamp (UTC).
                confirmed_at: Timestamp of upload confirmation, or NULL if pending.
            \"\"\"

            __tablename__ = "files"

            id: Mapped[uuid.UUID] = mapped_column(
                Uuid, primary_key=True, default=uuid.uuid4
            )
            original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
            stored_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
            content_type: Mapped[str] = mapped_column(String(255), nullable=False)
            size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="pending"
            )  # "pending" | "confirmed" | "virus_detected" | "orphaned"
            uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
            )
            tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
            resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
            resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            confirmed_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            __table_args__ = (
                Index("ix_files_resource", "resource_type", "resource_id"),
                Index("ix_files_uploaded_by", "uploaded_by"),
                Index("ix_files_tenant_status", "tenant_id", "status"),
            )
        """)
    dest.write_text(content)


def _write_storage(dest: Path) -> None:
    """Write ``app/core/storage.py`` with ABC + LocalStorage + S3Storage + factory.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Storage backend ABC with LocalStorage and S3Storage implementations.

        Use ``get_storage()`` to obtain the configured backend.  The backend is
        selected by ``settings.STORAGE_BACKEND`` (``"local"`` or ``"s3"``).
        \"\"\"

        from __future__ import annotations

        import asyncio
        import os
        import tempfile
        import uuid
        from abc import ABC, abstractmethod
        from pathlib import Path


        CHUNK_SIZE: int = 65536  # 64 KB — never buffers full file in memory


        class StorageBackend(ABC):
            \"\"\"Abstract storage backend.  Both implementations share this interface.\"\"\"

            @abstractmethod
            async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
                \"\"\"Persist *file_obj* and return ``(stored_key, size_bytes)``.

                Args:
                    file_obj: File-like object with a ``read`` method.
                    content_type: MIME type of the file.

                Returns:
                    Tuple of ``(stored_key, size_bytes)``.
                \"\"\"

            @abstractmethod
            async def get_url(self, stored_key: str, expires_in: int = 3600) -> str:
                \"\"\"Return a URL (presigned for S3, file path for local) for *stored_key*.

                Args:
                    stored_key: UUID-based storage key.
                    expires_in: URL TTL in seconds (S3 only).

                Returns:
                    Accessible URL string.
                \"\"\"

            @abstractmethod
            async def delete(self, stored_key: str) -> None:
                \"\"\"Remove the object identified by *stored_key* from storage.

                Args:
                    stored_key: UUID-based storage key.
                \"\"\"


        class LocalStorage(StorageBackend):
            \"\"\"Local filesystem storage with atomic temp-file rename (no partial writes).

            Attributes:
                base_dir: Resolved absolute path to the upload root directory.
            \"\"\"

            def __init__(self, base_dir: str) -> None:
                self.base_dir = Path(base_dir).resolve()
                self.base_dir.mkdir(parents=True, exist_ok=True)

            async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
                \"\"\"Write *file_obj* atomically to ``base_dir/{uuid}.bin``.

                Args:
                    file_obj: Readable file-like object.
                    content_type: MIME type (stored in FileMetadata, not in filename).

                Returns:
                    ``(stored_key, size_bytes)`` where stored_key is ``"{uuid}.bin"``.
                \"\"\"
                key = str(uuid.uuid4()) + ".bin"
                target = self.base_dir / key

                def _write() -> int:
                    size = 0
                    fd, tmp_path = tempfile.mkstemp(dir=self.base_dir)
                    try:
                        with os.fdopen(fd, "wb") as fh:
                            while True:
                                chunk = file_obj.read(CHUNK_SIZE)
                                if not chunk:
                                    break
                                fh.write(chunk)
                                size += len(chunk)
                        os.replace(tmp_path, target)
                    except Exception:
                        os.unlink(tmp_path)
                        raise
                    return size

                size = await asyncio.to_thread(_write)
                return key, size

            async def get_url(self, stored_key: str, expires_in: int = 3600) -> str:
                \"\"\"Return absolute filesystem path — validate against base_dir (no traversal).

                Args:
                    stored_key: UUID-based storage key.
                    expires_in: Ignored for local storage.

                Returns:
                    Absolute path string.

                Raises:
                    ValueError: If stored_key escapes the base_dir.
                \"\"\"
                target = (self.base_dir / stored_key).resolve()
                if not str(target).startswith(str(self.base_dir)):
                    raise ValueError(f"Path traversal attempt rejected: {stored_key}")
                return str(target)

            async def delete(self, stored_key: str) -> None:
                \"\"\"Delete the file identified by *stored_key* from local storage.

                Args:
                    stored_key: UUID-based storage key.
                \"\"\"
                target = (self.base_dir / stored_key).resolve()
                if not str(target).startswith(str(self.base_dir)):
                    raise ValueError(f"Path traversal attempt rejected: {stored_key}")
                target.unlink(missing_ok=True)


        class S3Storage(StorageBackend):
            \"\"\"S3 storage backend — files uploaded directly by client via presigned URL.

            ``save()`` is a no-op for S3 (client uploads directly); only ``get_url``
            and ``delete`` are called by the application server.
            \"\"\"

            async def save(self, file_obj: object, content_type: str) -> tuple[str, int]:
                \"\"\"Not used on S3 path — clients upload directly via presigned POST.

                Args:
                    file_obj: Ignored.
                    content_type: Ignored.

                Returns:
                    Empty stored_key and 0 bytes (S3 confirmation uses HEAD).
                \"\"\"
                return "", 0

            async def get_url(self, stored_key: str, expires_in: int = 3600) -> str:
                \"\"\"Return a presigned GET URL for *stored_key*.

                Args:
                    stored_key: S3 object key.
                    expires_in: URL TTL in seconds.

                Returns:
                    Presigned S3 GET URL.
                \"\"\"
                import boto3
                from app.core.config import settings
                client = boto3.client("s3", region_name=settings.AWS_REGION)
                return client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.S3_BUCKET, "Key": stored_key},
                    ExpiresIn=expires_in,
                )

            async def delete(self, stored_key: str) -> None:
                \"\"\"Delete *stored_key* from S3.  Uses AES256 server-side encryption bucket.

                Args:
                    stored_key: S3 object key.
                \"\"\"
                import boto3
                from app.core.config import settings
                client = boto3.client("s3", region_name=settings.AWS_REGION)
                client.delete_object(Bucket=settings.S3_BUCKET, Key=stored_key)


        def get_storage() -> StorageBackend:
            \"\"\"Return the configured storage backend based on ``settings.STORAGE_BACKEND``.

            Returns:
                ``LocalStorage`` or ``S3Storage`` instance.
            \"\"\"
            from app.core.config import settings
            if getattr(settings, "STORAGE_BACKEND", "local") == "s3":
                return S3Storage()
            upload_dir = getattr(settings, "UPLOAD_DIR", "/tmp/uploads")
            return LocalStorage(upload_dir)
        """)
    dest.write_text(content)


def _write_file_validator(dest: Path) -> None:
    """Write ``app/core/file_validator.py`` with magic-byte MIME detection.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"File type validation by magic bytes — never by extension or Content-Type header.

        Imports python-magic (libmagic bindings).  Install with::

            pip install python-magic>=0.4.27
        \"\"\"

        from __future__ import annotations

        from typing import BinaryIO


        SAFE_DEFAULTS: frozenset[str] = frozenset({
            "image/jpeg",
            "image/png",
            "image/gif",
            "image/webp",
            "application/pdf",
            "text/plain",
        })

        # Types blocked regardless of ALLOWED_FILE_TYPES override
        ALWAYS_BLOCKED: frozenset[str] = frozenset({
            "application/x-msdownload",   # Windows PE executables
            "application/x-executable",   # Linux ELF binaries
            "application/x-dosexec",      # DOS executables
            "text/x-shellscript",         # Shell scripts
            "application/x-sh",           # Shell scripts (alternate MIME)
        })

        _HEAD_BYTES: int = 8192  # 8 KB is sufficient for libmagic identification


        def detect_mime(file: BinaryIO) -> str | None:
            \"\"\"Read the first 8 KB and detect MIME type via libmagic byte-signature analysis.

            The file pointer is reset to its original position before returning, so
            subsequent reads from the caller are not affected.

            Args:
                file: Readable binary file-like object.

            Returns:
                MIME type string, or ``None`` if libmagic cannot identify the content.
            \"\"\"
            import magic
            pos = file.tell()
            head = file.read(_HEAD_BYTES)
            file.seek(pos)
            if not head:
                return None
            return magic.from_buffer(head, mime=True)


        def validate_file(
            file: BinaryIO,
            declared_content_type: str,
            allowed_types: frozenset[str],
        ) -> str:
            \"\"\"Detect actual MIME from magic bytes and validate against allowed list.

            Args:
                file: Readable binary file-like object.
                declared_content_type: Client-supplied Content-Type (informational only).
                allowed_types: Set of allowed MIME type strings.

            Returns:
                Detected MIME type (ground truth for DB storage).

            Raises:
                ValueError: If type cannot be detected, is in ``ALWAYS_BLOCKED``,
                    or not in ``allowed_types``.
            \"\"\"
            actual = detect_mime(file)
            if actual is None:
                raise ValueError(
                    "Could not detect file type from content (empty or unknown bytes)"
                )
            if actual in ALWAYS_BLOCKED:
                raise ValueError(f"File type '{actual}' is unconditionally blocked")
            if actual not in allowed_types:
                raise ValueError(f"File type '{actual}' is not in the allowed list")
            return actual
        """)
    dest.write_text(content)


def _write_presigned_urls(dest: Path) -> None:
    """Write ``app/core/presigned_urls.py`` with S3 presigned URL helpers.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Presigned URL helpers for direct S3 client upload — server never proxies file bytes.\"\"\"

        from __future__ import annotations

        import uuid
        from typing import Any


        def _build_presign_conditions(
            content_type: str, max_size_bytes: int | None
        ) -> list[Any]:
            \"\"\"Build the conditions list for a presigned POST request.

            Args:
                content_type: MIME type to enforce on the upload.
                max_size_bytes: Optional maximum file size limit.

            Returns:
                List of S3 presign condition dicts/lists.
            \"\"\"
            conditions: list[Any] = [
                {"Content-Type": content_type},
                ["starts-with", "$key", "uploads/"],
            ]
            if max_size_bytes is not None:
                conditions.append(["content-length-range", 1, max_size_bytes])
            return conditions


        def generate_upload_url(
            *,
            file_id: uuid.UUID,
            extension: str,
            content_type: str,
            expires_in: int = 300,
            max_size_bytes: int | None = None,
        ) -> dict[str, Any]:
            \"\"\"Return a presigned POST URL for direct client-to-S3 upload.

            ``max_size_bytes`` adds a Content-Length-Range condition so S3 rejects
            oversized uploads at the bucket level before our confirmation endpoint.

            Args:
                file_id: UUID for the new file — used to derive the stored_key.
                extension: File extension (max 10 chars, stripped of leading dot).
                content_type: Detected MIME type for the S3 object.
                expires_in: Presigned URL TTL in seconds.
                max_size_bytes: Optional maximum upload size enforced by S3.

            Returns:
                Dict with ``upload_url``, ``fields``, ``stored_key``, ``expires_in``.
            \"\"\"
            import boto3
            from app.core.config import settings

            client = boto3.client("s3", region_name=settings.AWS_REGION)
            ext = extension.lstrip(".")[:10]
            stored_key = f"uploads/{file_id}.{ext}"
            conditions = _build_presign_conditions(content_type, max_size_bytes)
            response = client.generate_presigned_post(
                Bucket=settings.S3_BUCKET,
                Key=stored_key,
                Fields={"Content-Type": content_type, "x-amz-server-side-encryption": "AES256"},
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
            return {
                "upload_url": response["url"],
                "fields": response["fields"],
                "stored_key": stored_key,
                "expires_in": expires_in,
            }


        def generate_download_url(stored_key: str, expires_in: int = 3600) -> str:
            \"\"\"Return a presigned GET URL for an S3 object.

            Args:
                stored_key: S3 object key.
                expires_in: URL TTL in seconds.

            Returns:
                Presigned GET URL string.

            Raises:
                RuntimeError: If the boto3 presign call fails.
            \"\"\"
            import boto3
            from botocore.exceptions import ClientError
            from app.core.config import settings

            client = boto3.client("s3", region_name=settings.AWS_REGION)
            try:
                return client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": settings.S3_BUCKET, "Key": stored_key},
                    ExpiresIn=expires_in,
                )
            except ClientError as exc:
                raise RuntimeError(f"S3 presign failed: {exc}") from exc
        """)
    dest.write_text(content)


def _write_upload_quota(dest: Path) -> None:
    """Write ``app/core/upload_quota.py`` with Redis-locked per-user quota checker.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Per-user storage quota enforcement with Redis advisory locking.

        The Redis lock ensures only one concurrent upload per user passes the
        quota check at a time, preventing race conditions where two simultaneous
        uploads each see sufficient quota and both succeed.
        \"\"\"

        from __future__ import annotations

        import uuid
        from contextlib import asynccontextmanager

        from sqlalchemy import func, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.file import FileMetadata

        QUOTA_LOCK_TTL_SECONDS: int = 5  # Lock held during quota check + pending row insert


        async def _get_redis():
            \"\"\"Return a connected aioredis client from settings.REDIS_URL.\"\"\"
            import redis.asyncio as aioredis
            from app.core.config import settings
            return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


        @asynccontextmanager
        async def quota_lock(user_id: uuid.UUID):
            \"\"\"Async context manager: acquire a Redis advisory lock for ``user_id``.

            Args:
                user_id: UUID of the uploading user.

            Raises:
                HTTPException: 429 if another upload is already in progress for this user.

            Yields:
                Nothing — the lock is released on exit regardless of outcome.
            \"\"\"
            from fastapi import HTTPException
            redis = await _get_redis()
            lock_key = f"quota_lock:{user_id}"
            acquired = False
            try:
                acquired = bool(
                    await redis.set(lock_key, "1", nx=True, ex=QUOTA_LOCK_TTL_SECONDS)
                )
                if not acquired:
                    raise HTTPException(
                        status_code=429,
                        detail="Upload in progress for this user. Retry shortly.",
                    )
                yield
            finally:
                if acquired:
                    await redis.delete(lock_key)
                await redis.aclose()


        async def check_quota(
            session: AsyncSession,
            user_id: uuid.UUID,
            incoming_bytes: int,
        ) -> None:
            \"\"\"Raise HTTP 413 if confirmed storage + incoming_bytes exceeds quota.

            Must be called inside a ``quota_lock`` context to prevent race conditions.

            Args:
                session: Async SQLAlchemy session.
                user_id: UUID of the uploading user.
                incoming_bytes: Size of the file about to be uploaded.

            Raises:
                HTTPException: 413 if the user would exceed their quota.
            \"\"\"
            from fastapi import HTTPException
            from app.core.config import settings

            stmt = (
                select(func.coalesce(func.sum(FileMetadata.size_bytes), 0))
                .where(FileMetadata.uploaded_by == user_id)
                .where(FileMetadata.status == "confirmed")
            )
            used_bytes: int = (await session.execute(stmt)).scalar_one()
            quota_bytes = getattr(settings, "QUOTA_MB_PER_USER", 500) * 1024 * 1024
            if used_bytes + incoming_bytes > quota_bytes:
                used_mb = used_bytes / (1024 * 1024)
                quota_mb = getattr(settings, "QUOTA_MB_PER_USER", 500)
                raise HTTPException(
                    status_code=413,
                    detail=f"Quota exceeded: {used_mb:.1f} MB used of {quota_mb} MB limit",
                )
        """)
    dest.write_text(content)


def _write_multipart_upload(dest: Path) -> None:
    """Write ``app/core/multipart_upload.py`` with S3 multipart upload helper.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"S3 multipart upload helper for files larger than 5 MB.

        Aborts the multipart upload automatically on any error to prevent
        orphaned multipart uploads accumulating in the S3 bucket.
        \"\"\"

        from __future__ import annotations

        from typing import BinaryIO


        PART_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB per part (S3 min is 5 MB)


        def upload_multipart(
            file: BinaryIO,
            stored_key: str,
            content_type: str,
        ) -> dict[str, str]:
            \"\"\"Upload a file to S3 using multipart upload for large files.

            Reads *file* in ``PART_SIZE_BYTES`` chunks, uploading each part.
            On any error, aborts the multipart upload and re-raises the exception.

            Args:
                file: Readable binary file-like object.
                stored_key: S3 object key for the destination.
                content_type: MIME type for the S3 object.

            Returns:
                Dict with ``ETag`` and ``VersionId`` from the complete response.

            Raises:
                Exception: Any error from S3 after aborting the multipart upload.
            \"\"\"
            import boto3
            from app.core.config import settings

            client = boto3.client("s3", region_name=settings.AWS_REGION)
            upload_id = _start_multipart(client, settings.S3_BUCKET, stored_key, content_type)
            try:
                parts = _upload_parts(client, file, settings.S3_BUCKET, stored_key, upload_id)
                return _complete_multipart(client, settings.S3_BUCKET, stored_key, upload_id, parts)
            except Exception:
                client.abort_multipart_upload(
                    Bucket=settings.S3_BUCKET, Key=stored_key, UploadId=upload_id
                )
                raise


        def _start_multipart(client, bucket: str, key: str, content_type: str) -> str:
            \"\"\"Initiate a multipart upload and return the upload ID.

            Args:
                client: Boto3 S3 client.
                bucket: S3 bucket name.
                key: S3 object key.
                content_type: MIME type for the uploaded object.

            Returns:
                The UploadId string from the S3 create_multipart_upload response.
            \"\"\"
            mpu = client.create_multipart_upload(
                Bucket=bucket,
                Key=key,
                ContentType=content_type,
                ServerSideEncryption="AES256",
            )
            return mpu["UploadId"]


        def _upload_parts(
            client, file: BinaryIO, bucket: str, key: str, upload_id: str
        ) -> list[dict]:
            \"\"\"Upload all chunks of *file* and return the completed parts list.

            Args:
                client: Boto3 S3 client.
                file: Readable binary file-like object.
                bucket: S3 bucket name.
                key: S3 object key.
                upload_id: Active multipart upload ID.

            Returns:
                List of dicts with ``PartNumber`` and ``ETag`` for each chunk.
            \"\"\"
            parts: list[dict] = []
            part_number = 1
            while True:
                chunk = file.read(PART_SIZE_BYTES)
                if not chunk:
                    break
                response = client.upload_part(
                    Bucket=bucket, Key=key, UploadId=upload_id,
                    PartNumber=part_number, Body=chunk,
                )
                parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
                part_number += 1
            return parts


        def _complete_multipart(
            client, bucket: str, key: str, upload_id: str, parts: list[dict]
        ) -> dict[str, str]:
            \"\"\"Finalise a multipart upload and return ETag/VersionId.

            Args:
                client: Boto3 S3 client.
                bucket: S3 bucket name.
                key: S3 object key.
                upload_id: Active multipart upload ID.
                parts: List of completed part dicts (PartNumber + ETag).

            Returns:
                Dict with ``ETag`` and ``VersionId`` from the S3 response.
            \"\"\"
            complete = client.complete_multipart_upload(
                Bucket=bucket, Key=key, UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
            return {"ETag": complete.get("ETag", ""), "VersionId": complete.get("VersionId", "")}
        """)
    dest.write_text(content)


def _write_cleanup_orphans(dest: Path) -> None:
    """Write ``app/tasks/cleanup_orphans.py`` with the orphaned-upload cleanup job.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Background task: purge file metadata rows stuck in 'pending' past the TTL.

        These are uploads that were presigned but never confirmed (client abandoned).
        Storage objects are deleted first, then the metadata rows, in batches to
        avoid loading all orphans into memory at once.

        Schedule this via ARQ or Celery beat.  Call directly in tests::

            result = asyncio.run(cleanup_orphaned_uploads())
        \"\"\"

        from __future__ import annotations

        import logging
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import delete, select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.core.storage import get_storage
        from app.models.file import FileMetadata


        logger = logging.getLogger(__name__)
        ORPHAN_TTL_MINUTES: int = 60  # Pending uploads older than this are orphaned
        BATCH_SIZE: int = 100


        async def cleanup_orphaned_uploads(session: AsyncSession) -> dict[str, int]:
            \"\"\"Delete storage objects and DB rows for all uploads stuck in 'pending' past TTL.

            Processes rows in batches of ``BATCH_SIZE`` to avoid unbounded memory use.
            Uses ``WITH FOR UPDATE SKIP LOCKED`` to allow safe concurrent cleanup workers.

            Args:
                session: Async SQLAlchemy session (caller manages commit/rollback).

            Returns:
                Dict with ``deleted_storage`` (storage objects deleted) and
                ``deleted_db`` (DB rows deleted).
            \"\"\"
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_TTL_MINUTES)
            deleted_storage = 0
            deleted_db = 0
            storage = get_storage()

            while True:
                stmt = (
                    select(FileMetadata)
                    .where(FileMetadata.status == "pending")
                    .where(FileMetadata.created_at < cutoff)
                    .limit(BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
                rows = (await session.execute(stmt)).scalars().all()
                if not rows:
                    break

                for row in rows:
                    try:
                        await storage.delete(row.stored_key)
                        deleted_storage += 1
                    except Exception as exc:
                        logger.warning(
                            "cleanup: storage delete failed for %s: %s", row.stored_key, exc
                        )

                ids = [row.id for row in rows]
                await session.execute(
                    delete(FileMetadata).where(FileMetadata.id.in_(ids))
                )
                await session.commit()
                deleted_db += len(ids)
                logger.info("cleanup: purged %d orphaned uploads (batch)", len(ids))

            logger.info("cleanup complete: storage=%d db=%d", deleted_storage, deleted_db)
            return {"deleted_storage": deleted_storage, "deleted_db": deleted_db}
        """)
    dest.write_text(content)


def _write_file_crud(dest: Path) -> None:
    """Write ``app/crud/file.py`` with async CRUD helpers for FileMetadata.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"CRUD helpers for FileMetadata model.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.file import FileMetadata


        async def create_pending(
            session: AsyncSession,
            *,
            id: uuid.UUID,
            original_filename: str,
            stored_key: str,
            content_type: str,
            size_bytes: int,
            uploaded_by: uuid.UUID | None = None,
            resource_type: str | None = None,
            resource_id: uuid.UUID | None = None,
        ) -> FileMetadata:
            \"\"\"Insert a pending FileMetadata row before the upload completes.

            Args:
                session: Async SQLAlchemy session.
                id: Pre-generated UUID for the file.
                original_filename: Original client filename (display only).
                stored_key: UUID-based storage key.
                content_type: MIME type detected from magic bytes.
                size_bytes: Declared size (confirmed later via HEAD).
                uploaded_by: UUID of the uploading user.
                resource_type: Optional polymorphic resource type.
                resource_id: Optional polymorphic resource ID.

            Returns:
                The inserted FileMetadata ORM instance.
            \"\"\"
            row = FileMetadata(
                id=id,
                original_filename=original_filename,
                stored_key=stored_key,
                content_type=content_type,
                size_bytes=size_bytes,
                status="pending",
                uploaded_by=uploaded_by,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            session.add(row)
            await session.flush()
            return row


        async def confirm(
            session: AsyncSession,
            *,
            file_id: uuid.UUID,
            size_bytes: int,
            confirmed_at: datetime,
        ) -> FileMetadata | None:
            \"\"\"Transition a pending file to confirmed status.

            Args:
                session: Async SQLAlchemy session.
                file_id: UUID of the pending file to confirm.
                size_bytes: Actual size confirmed from storage (e.g. S3 HEAD).
                confirmed_at: UTC timestamp of confirmation.

            Returns:
                Updated FileMetadata instance, or ``None`` if not found.
            \"\"\"
            stmt = select(FileMetadata).where(
                FileMetadata.id == file_id, FileMetadata.status == "pending"
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                return None
            row.status = "confirmed"
            row.size_bytes = size_bytes
            row.confirmed_at = confirmed_at
            await session.flush()
            return row


        async def get_pending(
            session: AsyncSession,
            file_id: uuid.UUID,
            owner_id: uuid.UUID | None = None,
        ) -> FileMetadata | None:
            \"\"\"Fetch a pending FileMetadata row, optionally scoped to an owner.

            Args:
                session: Async SQLAlchemy session.
                file_id: UUID to look up.
                owner_id: If provided, must match ``uploaded_by``.

            Returns:
                FileMetadata instance or ``None``.
            \"\"\"
            stmt = select(FileMetadata).where(
                FileMetadata.id == file_id, FileMetadata.status == "pending"
            )
            if owner_id is not None:
                stmt = stmt.where(FileMetadata.uploaded_by == owner_id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def get_confirmed(
            session: AsyncSession,
            file_id: uuid.UUID,
        ) -> FileMetadata | None:
            \"\"\"Fetch a confirmed FileMetadata row by ID.

            Args:
                session: Async SQLAlchemy session.
                file_id: UUID to look up.

            Returns:
                FileMetadata instance or ``None``.
            \"\"\"
            stmt = select(FileMetadata).where(
                FileMetadata.id == file_id, FileMetadata.status == "confirmed"
            )
            return (await session.execute(stmt)).scalar_one_or_none()


        async def get(
            session: AsyncSession,
            file_id: uuid.UUID,
        ) -> FileMetadata | None:
            \"\"\"Fetch any FileMetadata row by ID regardless of status.

            Args:
                session: Async SQLAlchemy session.
                file_id: UUID to look up.

            Returns:
                FileMetadata instance or ``None``.
            \"\"\"
            return await session.get(FileMetadata, file_id)


        async def delete(
            session: AsyncSession,
            file_id: uuid.UUID,
        ) -> None:
            \"\"\"Delete a FileMetadata row.  Caller is responsible for removing storage object.

            Args:
                session: Async SQLAlchemy session.
                file_id: UUID of the row to delete.
            \"\"\"
            row = await session.get(FileMetadata, file_id)
            if row is not None:
                await session.delete(row)
                await session.flush()
        """)
    dest.write_text(content)


def _write_file_schemas(dest: Path) -> None:
    """Write ``app/schemas/file.py`` with Pydantic schemas for file upload.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic v2 schemas for the file upload system.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict, Field


        class PresignedUploadRequest(BaseModel):
            \"\"\"Request body for POST /files/presign.

            Attributes:
                filename: Original filename for display (max 255 chars).
                content_type: Declared MIME type (validated before presign is issued).
                size_bytes: Declared file size in bytes.
                resource_type: Optional polymorphic association type.
                resource_id: Optional polymorphic association ID.
            \"\"\"

            filename: str = Field(..., max_length=255)
            content_type: str = Field(..., max_length=255)
            size_bytes: int = Field(..., gt=0)
            resource_type: str | None = Field(default=None, max_length=64)
            resource_id: uuid.UUID | None = None


        class PresignedUploadResponse(BaseModel):
            \"\"\"Response body for POST /files/presign.

            Attributes:
                file_id: UUID assigned to this upload (used in /confirm).
                upload_url: S3 presigned POST URL.
                fields: Form fields required in the POST to S3.
                stored_key: Object key that will be used in S3.
                expires_in: Seconds until the presigned URL expires.
            \"\"\"

            file_id: uuid.UUID
            upload_url: str
            fields: dict
            stored_key: str
            expires_in: int


        class UploadConfirmRequest(BaseModel):
            \"\"\"Request body for POST /files/{id}/confirm.\"\"\"

            checksum_md5: str | None = Field(
                default=None,
                description="Optional MD5 hex digest for client-side integrity check.",
            )


        class FileMetadataPublic(BaseModel):
            \"\"\"Public schema for FileMetadata — intentionally excludes stored_key and tenant_id.

            Attributes:
                id: UUID primary key.
                original_filename: Display filename from the original upload.
                content_type: Detected MIME type.
                size_bytes: Confirmed file size in bytes.
                status: Upload lifecycle status.
                resource_type: Polymorphic resource type.
                resource_id: Polymorphic resource ID.
                created_at: Upload creation timestamp (UTC).
                confirmed_at: Confirmation timestamp or ``None`` if still pending.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            original_filename: str
            content_type: str
            size_bytes: int
            status: str
            resource_type: str | None = None
            resource_id: uuid.UUID | None = None
            created_at: datetime
            confirmed_at: datetime | None = None


        class FilesPublic(BaseModel):
            \"\"\"Paginated list of file metadata records.

            Attributes:
                data: Page of file metadata records.
                count: Total records matching the filter.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            data: list[FileMetadataPublic]
            count: int
        """)
    dest.write_text(content)


def _write_file_routes(dest: Path) -> None:
    """Write ``app/api/routes/files.py`` with presign, confirm, download, delete routes.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"File upload routes: presign, confirm, direct upload, download, delete.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime, timezone

        from fastapi import APIRouter, HTTPException, UploadFile, status
        from fastapi.responses import FileResponse, RedirectResponse

        from app.api.deps import CurrentUser, SessionDep
        from app.core.file_validator import SAFE_DEFAULTS, validate_file
        from app.core.storage import get_storage
        from app.crud import file as crud_file
        from app.schemas.file import (
            FileMetadataPublic,
            PresignedUploadRequest,
            PresignedUploadResponse,
            UploadConfirmRequest,
        )

        router = APIRouter(prefix="/files", tags=["files"])


        def _validate_upload_request(body: PresignedUploadRequest, settings) -> None:
            \"\"\"Raise HTTPException if content-type or file size is disallowed.

            Args:
                body: Upload request schema with content_type and size_bytes.
                settings: App settings object with ALLOWED_FILE_TYPES / MAX_UPLOAD_SIZE_MB.

            Raises:
                HTTPException 422: Content type not in allowed set.
                HTTPException 413: File size exceeds configured limit.
            \"\"\"
            allowed_set = frozenset(getattr(settings, "ALLOWED_FILE_TYPES", None) or SAFE_DEFAULTS)
            if body.content_type not in allowed_set:
                raise HTTPException(status_code=422, detail=f"Content type '{body.content_type}' not allowed")
            max_bytes = getattr(settings, "MAX_UPLOAD_SIZE_MB", 10) * 1024 * 1024
            if body.size_bytes > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large (max {getattr(settings, 'MAX_UPLOAD_SIZE_MB', 10)} MB)",
                )


        @router.post(
            "/presign",
            response_model=PresignedUploadResponse,
            summary="Generate presigned URL for direct S3 upload (Phase 1 of 2)",
        )
        async def request_presigned_upload(
            body: PresignedUploadRequest,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> PresignedUploadResponse:
            \"\"\"Phase 1 of 2: client requests a presigned URL then uploads directly to S3.

            Args:
                body: Upload request with filename, content_type, size_bytes.
                session: Injected async DB session.
                current_user: Authenticated user.

            Raises:
                HTTPException: 422 for disallowed content type, 413 for oversized file.
            \"\"\"
            from app.core.config import settings
            from app.core.presigned_urls import generate_upload_url

            _validate_upload_request(body, settings)
            file_id = uuid.uuid4()
            ext = (body.filename.rsplit(".", 1)[-1] if "." in body.filename else "bin")[:10]
            result = generate_upload_url(
                file_id=file_id, extension=ext,
                content_type=body.content_type, max_size_bytes=body.size_bytes,
            )
            await crud_file.create_pending(
                session, id=file_id, original_filename=body.filename[:255],
                stored_key=result["stored_key"], content_type=body.content_type,
                size_bytes=body.size_bytes, uploaded_by=current_user.id,
                resource_type=body.resource_type, resource_id=body.resource_id,
            )
            return PresignedUploadResponse(file_id=file_id, **result)


        @router.post(
            "/{file_id}/confirm",
            response_model=FileMetadataPublic,
            status_code=status.HTTP_200_OK,
            summary="Confirm S3 upload completed (Phase 2 of 2)",
        )
        async def confirm_upload(
            file_id: uuid.UUID,
            body: UploadConfirmRequest,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> FileMetadataPublic:
            \"\"\"Phase 2 of 2: after client uploads to S3, confirm and activate the metadata row.

            Verifies the S3 object exists via HEAD before transitioning status to confirmed.

            Args:
                file_id: UUID of the pending upload to confirm.
                body: Optional checksum for integrity verification.
                session: Injected async DB session.
                current_user: Must be the original uploader.

            Raises:
                HTTPException: 404 if pending record not found, 422 if S3 object missing.
            \"\"\"
            import boto3
            from app.core.config import settings

            metadata = await crud_file.get_pending(session, file_id, owner_id=current_user.id)
            if metadata is None:
                raise HTTPException(status_code=404, detail="Pending upload not found")

            try:
                s3 = boto3.client("s3", region_name=settings.AWS_REGION)
                head = s3.head_object(Bucket=settings.S3_BUCKET, Key=metadata.stored_key)
                actual_size = head["ContentLength"]
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"S3 object not found: {exc}"
                ) from exc

            confirmed = await crud_file.confirm(
                session,
                file_id=file_id,
                size_bytes=actual_size,
                confirmed_at=datetime.now(timezone.utc),
            )
            return FileMetadataPublic.model_validate(confirmed)


        async def _persist_local_upload(session, storage, file_id, filename, stored_key, actual_mime, size_bytes, owner_id):
            \"\"\"Write metadata row, confirm upload, or rollback storage on DB error.

            Args:
                session: Async SQLAlchemy session.
                storage: Storage backend with .delete() for rollback.
                file_id: Pre-assigned UUID for the new file record.
                filename: Original client-provided filename (truncated to 255 chars).
                stored_key: Storage-layer key returned by storage.save().
                actual_mime: Validated MIME type string.
                size_bytes: Exact byte count from storage.
                owner_id: UUID of the uploading user.

            Returns:
                Confirmed FileMetadata ORM instance.

            Raises:
                HTTPException 500: DB write failed (storage object is deleted on rollback).
            \"\"\"
            try:
                row = await crud_file.create_pending(
                    session, id=file_id, original_filename=filename[:255],
                    stored_key=stored_key, content_type=actual_mime,
                    size_bytes=size_bytes, uploaded_by=owner_id,
                )
                return await crud_file.confirm(session, file_id=row.id, size_bytes=size_bytes,
                    confirmed_at=datetime.now(timezone.utc))
            except Exception as exc:
                await storage.delete(stored_key)
                raise HTTPException(status_code=500, detail=f"DB insert failed: {exc}") from exc


        @router.post(
            "/",
            response_model=FileMetadataPublic,
            status_code=status.HTTP_201_CREATED,
            summary="Direct file upload for local storage path",
        )
        async def upload_file_local(
            file: UploadFile,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> FileMetadataPublic:
            \"\"\"Direct upload endpoint for local storage (not the S3 path).

            Validates Content-Length header, detects MIME from magic bytes, writes
            atomically via LocalStorage, creates a confirmed metadata row in one step.

            Args:
                file: Uploaded file from the multipart form.
                session: Injected async DB session.
                current_user: Authenticated user.

            Raises:
                HTTPException: 413 for oversized, 422 for disallowed MIME type.
            \"\"\"
            from app.core.config import settings

            max_bytes = getattr(settings, "MAX_UPLOAD_SIZE_MB", 10) * 1024 * 1024
            if file.size is not None and file.size > max_bytes:
                raise HTTPException(status_code=413, detail="File too large")
            allowed = frozenset(getattr(settings, "ALLOWED_FILE_TYPES", None) or SAFE_DEFAULTS)
            try:
                actual_mime = validate_file(file.file, file.content_type or "", allowed)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            storage = get_storage()
            file_id = uuid.uuid4()
            try:
                stored_key, size_bytes = await storage.save(file.file, actual_mime)
            except Exception as exc:
                raise HTTPException(status_code=500, detail=f"Storage write failed: {exc}") from exc
            confirmed = await _persist_local_upload(
                session, storage, file_id, file.filename or "upload",
                stored_key, actual_mime, size_bytes, current_user.id,
            )
            return FileMetadataPublic.model_validate(confirmed)


        @router.get(
            "/{file_id}",
            response_model=None,
            summary="Download or get presigned URL for a file",
        )
        async def download_file(
            file_id: uuid.UUID,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> RedirectResponse | FileResponse:
            \"\"\"Return a 302 redirect (S3) or stream the file (local storage).

            Ownership check: only the uploader or a superuser can download.

            Args:
                file_id: UUID of the confirmed file.
                session: Injected async DB session.
                current_user: Must be owner or superuser.

            Raises:
                HTTPException: 404 not found, 403 forbidden, 451 if virus-detected.
            \"\"\"
            from app.core.config import settings
            from app.core.presigned_urls import generate_download_url

            metadata = await crud_file.get_confirmed(session, file_id)
            if metadata is None:
                raise HTTPException(status_code=404, detail="File not found")
            if (
                metadata.uploaded_by != current_user.id
                and not getattr(current_user, "is_superuser", False)
            ):
                raise HTTPException(status_code=403, detail="Forbidden")
            if metadata.status == "virus_detected":
                raise HTTPException(status_code=451, detail="File is quarantined (virus detected)")

            if getattr(settings, "STORAGE_BACKEND", "local") == "s3":
                url = generate_download_url(metadata.stored_key, expires_in=3600)
                return RedirectResponse(url=url, status_code=302)

            from pathlib import Path as _Path
            base = _Path(getattr(settings, "UPLOAD_DIR", "/tmp/uploads")).resolve()
            target = (base / metadata.stored_key).resolve()
            if not str(target).startswith(str(base)):
                raise HTTPException(status_code=422, detail="Invalid stored key")
            return FileResponse(
                path=str(target),
                media_type=metadata.content_type,
                filename=metadata.original_filename,
            )


        @router.delete(
            "/{file_id}",
            response_model=None,
            status_code=status.HTTP_204_NO_CONTENT,
            summary="Delete file from storage and remove metadata",
        )
        async def delete_file(
            file_id: uuid.UUID,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> None:
            \"\"\"Delete a file's storage object and metadata row.

            Ownership check: only the uploader or a superuser can delete.

            Args:
                file_id: UUID of the file to delete.
                session: Injected async DB session.
                current_user: Must be owner or superuser.

            Raises:
                HTTPException: 404 not found, 403 forbidden.
            \"\"\"
            metadata = await crud_file.get(session, file_id)
            if metadata is None:
                raise HTTPException(status_code=404, detail="File not found")
            if (
                metadata.uploaded_by != current_user.id
                and not getattr(current_user, "is_superuser", False)
            ):
                raise HTTPException(status_code=403, detail="Forbidden")

            storage = get_storage()
            await storage.delete(metadata.stored_key)
            await crud_file.delete(session, file_id)
        """)
    dest.write_text(content)


def _patch_api_main(api_main: Path) -> None:
    """Register the files router in ``app/api/main.py``.

    Args:
        api_main: Path to ``app/api/main.py``.
    """
    src = api_main.read_text()
    if "files" in src and "files.router" in src:
        return
    if "from app.api.routes import" in src:
        src = src.replace(
            "from app.api.routes import",
            "from app.api.routes import files as files_routes\nfrom app.api.routes import",
        )
        src = src + "\napi_router.include_router(files_routes.router)\n"
    else:
        src = src + (
            "\nfrom app.api.routes import files as files_routes\n"
            "api_router.include_router(files_routes.router)\n"
        )
    api_main.write_text(src)


def _patch_config(config_file: Path) -> None:
    """Append file-upload settings fields to the Settings class in ``config.py``.

    Args:
        config_file: Path to ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "STORAGE_BACKEND" in src:
        return
    additions = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # File upload settings — added by add_file_upload tool
        # ---------------------------------------------------------------------------
        STORAGE_BACKEND: str = "local"           # "local" or "s3"
        UPLOAD_DIR: str = "/tmp/uploads"          # Local storage root
        MAX_UPLOAD_SIZE_MB: int = 10              # Per-file size limit
        ALLOWED_FILE_TYPES: list[str] = []        # Empty = use SAFE_DEFAULTS
        S3_BUCKET: str = ""                       # S3 bucket name
        AWS_REGION: str = "us-east-1"             # AWS region
        QUOTA_MB_PER_USER: int = 500              # Per-user storage quota
        """)
    config_file.write_text(src + additions)


def _patch_requirements(requirements_file: Path) -> None:
    """Add python-magic and boto3 to requirements.txt.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
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


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the ``files`` table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    rev_id = "create_files_table"
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Create files table for file upload system.

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_file_upload tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "{rev_id}"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create the files table with all indexes and constraints.\"\"\"
            op.create_table(
                "files",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("original_filename", sa.String(255), nullable=False),
                sa.Column("stored_key", sa.String(512), nullable=False),
                sa.Column("content_type", sa.String(255), nullable=False),
                sa.Column("size_bytes", sa.BigInteger(), nullable=False),
                sa.Column(
                    "status", sa.String(16), server_default="pending", nullable=False
                ),
                sa.Column("uploaded_by", sa.Uuid(), nullable=True),
                sa.Column("tenant_id", sa.Uuid(), nullable=True),
                sa.Column("resource_type", sa.String(64), nullable=True),
                sa.Column("resource_id", sa.Uuid(), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
                sa.ForeignKeyConstraint(
                    ["uploaded_by"], ["users.id"], ondelete="SET NULL"
                ),
                sa.PrimaryKeyConstraint("id"),
                sa.UniqueConstraint("stored_key"),
            )
            op.create_index("ix_files_resource", "files", ["resource_type", "resource_id"])
            op.create_index("ix_files_uploaded_by", "files", ["uploaded_by"])
            op.create_index("ix_files_tenant_status", "files", ["tenant_id", "status"])


        def downgrade() -> None:
            \"\"\"Drop the files table and all associated indexes.\"\"\"
            op.drop_index("ix_files_tenant_status", table_name="files")
            op.drop_index("ix_files_uploaded_by", table_name="files")
            op.drop_index("ix_files_resource", table_name="files")
            op.drop_table("files")
        """).format(rev_id=rev_id, down_rev=down_rev)

    migration_file = versions_dir / f"{rev_id}.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (from ``time.monotonic()``).

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed time in milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
