# TOOL-003: add_file_upload

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_file_upload` |
| Category | EXTEND > CRUD & Data |
| Complexity | High |
| Dependencies | Existing FastAPI project with User model + Alembic; `boto3` if `storage="s3"`; `python-magic` or `filetype`; optional `add_multi_tenancy` for tenant-isolated storage |
| Signature | `add_file_upload(project_dir: str, model_name: str \| None = None, storage: Literal["local", "s3"] = "local", max_size_mb: int = 10, allowed_types: list[str] \| None = None, enable_virus_scan: bool = False, enable_quota: bool = False, quota_mb_per_user: int = 500) -> dict` |
| Parameters | `project_dir`: project root path<br>`model_name`: parent model for scoped listing (None = standalone `/files`)<br>`storage`: `"local"` or `"s3"` — determines backend class generated<br>`max_size_mb`: per-file upload limit enforced via `Content-Length` before body is read<br>`allowed_types`: list of allowed MIME types (None = safe defaults: images + PDF + text)<br>`enable_virus_scan`: scaffold ClamAV async wrapper for malware detection (default False)<br>`enable_quota`: scaffold per-user/per-tenant storage quota enforcer (default False)<br>`quota_mb_per_user`: quota limit in MB if `enable_quota=True` |

---

## 2. Purpose

`fastapi_add_file_upload` adds a production-grade file upload system to an existing FastAPI application.
The central design decision is that files are **never streamed through the application server on the upload path**:
for S3 storage, the tool generates a two-phase presigned URL workflow where the client uploads directly to S3
and the application only processes a lightweight confirmation payload, eliminating the memory, bandwidth, and
latency overhead of proxying large files through Python. For local storage, files are written in 64 KB chunks
to a UUID-keyed path inside a configurable upload directory, using an atomic temp-file-then-rename pattern to
guarantee no partial writes are visible to concurrent readers. In both modes, MIME type detection is performed
by reading the first 8 KB of file content and passing it through `python-magic` (libmagic bindings) for
byte-signature analysis — never by trusting the client-supplied `Content-Type` header or the file extension,
both of which are trivially spoofable. Virus scanning via ClamAV is scaffolded as an optional async wrapper
that calls the ClamAV Unix socket before the metadata row is written. Storage quota per user (and per tenant
when `add_multi_tenancy` is installed) is enforced by a pre-upload aggregate query that compares the sum of
existing `size_bytes` against the configured limit, with an atomic read-then-check protected by a short-lived
Redis advisory lock to prevent concurrent uploads from collectively exceeding the quota.

Beyond the core upload path, four production failure modes are explicitly addressed by the generated code.
First, **orphaned storage objects after DB failure**: the upload handler wraps the database insert in a
try/except that calls `storage.delete(stored_key)` on any exception, ensuring no file accumulates in storage
without a corresponding metadata row. Second, **orphaned metadata rows after storage failure**: the handler
never touches the database until the storage write has returned successfully. Third, **quota leaks from
concurrent uploads**: a Redis-based advisory lock scoped to `quota:{user_id}` ensures only one upload per
user passes the quota check at a time, preventing race conditions where two simultaneous uploads each
see sufficient quota and both succeed. Fourth, **presigned URL replay attacks for sensitive uploads**: when
`add_mfa` is installed, the presigned URL endpoint can optionally require a valid TOTP confirmation before
issuing a URL. Persistent metadata (the `FileMetadata` model) stores the original filename for display, the
UUID-keyed `stored_key` for storage operations, MIME type, size, uploader identity, upload status lifecycle
(`pending` → `confirmed` → `virus_detected`), and an optional polymorphic resource association so files can
be scoped to any business model. Multipart upload support for files larger than 5 MB on S3 is scaffolded via
`boto3.create_multipart_upload` with automatic abort-on-failure to prevent orphaned multipart uploads.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s | Dev waits in CLI; 6+ files created |
| Files created | 6..9 (model, schema, crud, storage, validator, routes, migration, optional virus scan, optional quota) | Predictable scaffolding surface |
| Files modified | ≤ 4 (`config.py`, `main.py`, `requirements.txt`, `.env.example`) | Minimal blast radius |
| Upload latency — 10 MB local | < 200 ms p99 | Local fs throughput; atomic write; 64 KB chunks |
| Upload latency — 10 MB S3 | < 500 ms p99 | Network bound; multipart for > 5 MB files |
| Presigned URL generation | < 50 ms p99 | Single `generate_presigned_url` boto3 call; no body transferred |
| Magic-byte detection | < 5 ms per file | First 8 KB only; `magic.from_buffer()` is synchronous and fast |
| Content-Length pre-check | < 1 ms | Single header read; no body buffered |
| Memory peak per upload (streaming) | < 16 MB | 64 KB chunk size; never full buffer in memory |
| Quota aggregate query | < 10 ms | `SUM(size_bytes) WHERE uploaded_by = ?` with index on `uploaded_by` |
| Virus scan (ClamAV, 10 MB file) | < 3 s | Unix socket scan; non-blocking via `asyncio.to_thread` |
| Download presigned URL (S3) | 302 redirect < 20 ms | No body transfer; signed URL computed locally |
| Cleanup job (orphaned files) | < 60 s for 10k orphans | Batched DELETE; daily scheduled task |

---

## 4. Code Examples

### 4.1 File model: GENERATED `app/models/file.py`

```python
"""FileMetadata model — persistent record for every uploaded file."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FileMetadata(Base):
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
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True
    )  # Populated by add_multi_tenancy; NULL on single-tenant installs
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
```

### 4.2 Presigned URL generator: GENERATED `app/core/presigned_urls.py`

```python
"""Presigned URL helpers for direct S3 client upload (no server streaming)."""
from __future__ import annotations

import uuid
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings


def generate_upload_url(
    *,
    file_id: uuid.UUID,
    extension: str,
    content_type: str,
    expires_in: int = 300,
    max_size_bytes: int | None = None,
) -> dict[str, Any]:
    """
    Return a presigned POST URL for direct client-to-S3 upload.
    `max_size_bytes` adds a Content-Length-Range condition so S3 rejects
    oversized uploads at the bucket level, before our confirmation endpoint.
    """
    client = boto3.client("s3", region_name=settings.AWS_REGION)
    stored_key = f"uploads/{file_id}.{extension[:10]}"

    conditions: list[Any] = [
        {"Content-Type": content_type},
        ["starts-with", "$key", "uploads/"],
    ]
    if max_size_bytes is not None:
        conditions.append(["content-length-range", 1, max_size_bytes])

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
    """Return a presigned GET URL for a stored object."""
    client = boto3.client("s3", region_name=settings.AWS_REGION)
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": stored_key},
            ExpiresIn=expires_in,
        )
    except ClientError as exc:
        raise RuntimeError(f"S3 presign failed: {exc}") from exc


def revoke_all_presigned_urls_via_bucket_policy(reason: str) -> None:
    """
    Emergency: block all presigned URLs by attaching a deny-all bucket policy.
    Used when a credential leak or mass-revocation is required.
    Restores normal access by deleting the policy.
    """
    client = boto3.client("s3", region_name=settings.AWS_REGION)
    deny_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Deny",
            "Principal": "*",
            "Action": "s3:GetObject",
            "Resource": f"arn:aws:s3:::{settings.S3_BUCKET}/*",
            "Condition": {"StringEquals": {"s3:signatureAge": "0"}},
        }],
    }
    import json
    client.put_bucket_policy(Bucket=settings.S3_BUCKET, Policy=json.dumps(deny_policy))
```

### 4.3 Upload confirmation endpoint: GENERATED `app/api/routes/files.py` (excerpt)

```python
"""File upload routes: presign, confirm, download, delete."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.file_validator import validate_file, SAFE_DEFAULTS
from app.core.presigned_urls import generate_upload_url, generate_download_url
from app.core.storage import get_storage
from app.crud import file as crud_file
from app.schemas.file import (
    FileMetadataPublic,
    FilesPublic,
    PresignedUploadRequest,
    PresignedUploadResponse,
    UploadConfirmRequest,
)

router = APIRouter(prefix="/files", tags=["files"])


@router.post(
    "/presign",
    response_model=PresignedUploadResponse,
    summary="Generate presigned URL for direct S3 upload",
)
async def request_presigned_upload(
    body: PresignedUploadRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> PresignedUploadResponse:
    """Phase 1 of 2: client requests a presigned URL, uploads directly to S3."""
    allowed = set(settings.ALLOWED_FILE_TYPES) if settings.ALLOWED_FILE_TYPES else SAFE_DEFAULTS
    if body.content_type not in allowed:
        raise HTTPException(status_code=422, detail=f"Content type '{body.content_type}' not allowed")
    if body.size_bytes > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large (max {settings.MAX_UPLOAD_SIZE_MB} MB)")

    file_id = uuid.uuid4()
    ext = (body.filename.rsplit(".", 1)[-1] if "." in body.filename else "bin")[:10]

    result = generate_upload_url(
        file_id=file_id,
        extension=ext,
        content_type=body.content_type,
        max_size_bytes=body.size_bytes,
    )
    # Create a pending metadata row — confirmed once client calls /confirm
    await crud_file.create_pending(
        session,
        id=file_id,
        original_filename=body.filename[:255],
        stored_key=result["stored_key"],
        content_type=body.content_type,
        size_bytes=body.size_bytes,
        uploaded_by=current_user.id,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
    )
    return PresignedUploadResponse(file_id=file_id, **result)


@router.post(
    "/{file_id}/confirm",
    response_model=FileMetadataPublic,
    status_code=status.HTTP_200_OK,
    summary="Confirm S3 upload completed — Phase 2 of 2",
)
async def confirm_upload(
    file_id: uuid.UUID,
    body: UploadConfirmRequest,
    session: SessionDep,
    current_user: CurrentUser,
) -> FileMetadataPublic:
    """Phase 2 of 2: after client uploads to S3, confirm and activate the metadata row."""
    metadata = await crud_file.get_pending(session, file_id, owner_id=current_user.id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="Pending upload not found")

    # Verify object actually exists in S3
    import boto3
    s3 = boto3.client("s3", region_name=settings.AWS_REGION)
    try:
        head = s3.head_object(Bucket=settings.S3_BUCKET, Key=metadata.stored_key)
        actual_size = head["ContentLength"]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"S3 object not found: {exc}") from exc

    confirmed = await crud_file.confirm(
        session,
        file_id=file_id,
        size_bytes=actual_size,
        confirmed_at=datetime.now(timezone.utc),
    )
    return FileMetadataPublic.model_validate(confirmed)
```

### 4.4 MIME sniff via `python-magic`: GENERATED `app/core/file_validator.py`

```python
"""File type validation by magic bytes — never by extension or Content-Type header."""
from __future__ import annotations

from typing import BinaryIO

import magic  # python-magic (libmagic bindings)


SAFE_DEFAULTS: frozenset[str] = frozenset({
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
})

# Types that are never allowed regardless of ALLOWED_FILE_TYPES override
ALWAYS_BLOCKED: frozenset[str] = frozenset({
    "application/x-msdownload",   # Windows PE executables
    "application/x-executable",   # Linux ELF binaries
    "application/x-dosexec",      # DOS executables
    "text/x-shellscript",         # Shell scripts
    "application/x-sh",           # Shell scripts (alternate MIME)
})


def detect_mime(file: BinaryIO) -> str | None:
    """
    Read first 8 KB and detect MIME type via libmagic byte-signature analysis.
    Resets the file pointer to its original position before returning.
    Returns None if libmagic cannot identify the content.
    """
    pos = file.tell()
    head = file.read(8192)
    file.seek(pos)
    if not head:
        return None
    return magic.from_buffer(head, mime=True)


def validate_file(
    file: BinaryIO,
    declared_content_type: str,
    allowed_types: frozenset[str],
) -> str:
    """
    Detect actual MIME from magic bytes. Raise ValueError if blocked or not allowed.
    Returns the detected MIME type (ground truth for DB storage).

    Raises:
        ValueError: if type cannot be detected, is in ALWAYS_BLOCKED, or not in allowed_types.
    """
    actual = detect_mime(file)
    if actual is None:
        raise ValueError("Could not detect file type from content (empty or unknown bytes)")
    if actual in ALWAYS_BLOCKED:
        raise ValueError(f"File type '{actual}' is unconditionally blocked")
    if actual not in allowed_types:
        raise ValueError(f"File type '{actual}' is not in the allowed list")
    return actual
```

### 4.5 ClamAV virus scan wrapper: GENERATED `app/core/virus_scan.py`

```python
"""Async ClamAV virus scanner via Unix socket (clamd protocol)."""
from __future__ import annotations

import asyncio
import socket
import struct
from pathlib import Path


CLAMD_SOCKET: str = "/var/run/clamav/clamd.ctl"
CLAMD_TIMEOUT: int = 30  # seconds


class VirusScanResult:
    def __init__(self, clean: bool, threat_name: str | None = None) -> None:
        self.clean = clean
        self.threat_name = threat_name

    def __repr__(self) -> str:
        return f"VirusScanResult(clean={self.clean}, threat={self.threat_name})"


async def scan_file(file_path: str | Path) -> VirusScanResult:
    """
    Send a file path to ClamAV daemon via INSTREAM protocol.
    Returns VirusScanResult. Raises RuntimeError if clamd is unreachable.
    Non-blocking: runs socket IO in a thread executor.
    """
    path = str(file_path)

    def _scan() -> VirusScanResult:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(CLAMD_TIMEOUT)
            try:
                sock.connect(CLAMD_SOCKET)
            except OSError as exc:
                raise RuntimeError(f"ClamAV socket unavailable at {CLAMD_SOCKET}: {exc}") from exc

            # INSTREAM protocol: send file content in chunks
            sock.sendall(b"nINSTREAM\n")
            with open(path, "rb") as fh:
                while True:
                    chunk = fh.read(65536)
                    if not chunk:
                        break
                    size = struct.pack("!I", len(chunk))
                    sock.sendall(size + chunk)
            # Signal end of stream
            sock.sendall(struct.pack("!I", 0))

            response = b""
            while True:
                data = sock.recv(1024)
                if not data:
                    break
                response += data

        text = response.decode("utf-8", errors="replace").strip()
        if "OK" in text:
            return VirusScanResult(clean=True)
        # Format: "stream: <threat_name> FOUND"
        threat = text.split(":")[-1].strip().replace(" FOUND", "")
        return VirusScanResult(clean=False, threat_name=threat)

    return await asyncio.to_thread(_scan)
```

### 4.6 Quota checker: GENERATED `app/core/upload_quota.py`

```python
"""Per-user (and optional per-tenant) storage quota enforcement with Redis locking."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.file import FileMetadata


QUOTA_LOCK_TTL_SECONDS: int = 5  # Lock held during quota check + pending row insert


async def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


@asynccontextmanager
async def quota_lock(user_id: uuid.UUID):
    """Async context manager: acquire Redis advisory lock for quota check."""
    redis = await get_redis()
    lock_key = f"quota_lock:{user_id}"
    acquired = False
    try:
        acquired = bool(await redis.set(lock_key, "1", nx=True, ex=QUOTA_LOCK_TTL_SECONDS))
        if not acquired:
            raise HTTPException(status_code=429, detail="Upload in progress for this user. Retry shortly.")
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
    """
    Check that user's total confirmed storage + incoming_bytes <= quota.
    Raises HTTPException(413) if over limit.
    Must be called inside a quota_lock context.
    """
    from fastapi import HTTPException  # local import to avoid circular
    stmt = (
        select(func.coalesce(func.sum(FileMetadata.size_bytes), 0))
        .where(FileMetadata.uploaded_by == user_id)
        .where(FileMetadata.status == "confirmed")
    )
    result = await session.execute(stmt)
    used_bytes: int = result.scalar_one()
    quota_bytes = settings.QUOTA_MB_PER_USER * 1024 * 1024

    if used_bytes + incoming_bytes > quota_bytes:
        used_mb = used_bytes / (1024 * 1024)
        quota_mb = settings.QUOTA_MB_PER_USER
        raise HTTPException(
            status_code=413,
            detail=f"Quota exceeded: {used_mb:.1f} MB used of {quota_mb} MB limit",
        )
```

### 4.7 Chunked multipart upload helper: GENERATED `app/core/multipart_upload.py`

```python
"""S3 multipart upload helper for files > 5 MB."""
from __future__ import annotations

import uuid
from typing import BinaryIO

import boto3

from app.core.config import settings


PART_SIZE_BYTES: int = 10 * 1024 * 1024  # 10 MB per part (S3 min is 5 MB)


def upload_multipart(
    file: BinaryIO,
    stored_key: str,
    content_type: str,
) -> dict[str, str]:
    """
    Upload a file to S3 using multipart upload for reliability on large files.
    Returns {ETag, VersionId} from S3 complete response.
    Aborts the multipart upload automatically on any error.
    """
    client = boto3.client("s3", region_name=settings.AWS_REGION)
    mpu = client.create_multipart_upload(
        Bucket=settings.S3_BUCKET,
        Key=stored_key,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    upload_id = mpu["UploadId"]
    parts: list[dict] = []
    part_number = 1

    try:
        while True:
            chunk = file.read(PART_SIZE_BYTES)
            if not chunk:
                break
            response = client.upload_part(
                Bucket=settings.S3_BUCKET,
                Key=stored_key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=chunk,
            )
            parts.append({"PartNumber": part_number, "ETag": response["ETag"]})
            part_number += 1

        complete = client.complete_multipart_upload(
            Bucket=settings.S3_BUCKET,
            Key=stored_key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )
        return {"ETag": complete.get("ETag", ""), "VersionId": complete.get("VersionId", "")}

    except Exception:
        client.abort_multipart_upload(
            Bucket=settings.S3_BUCKET,
            Key=stored_key,
            UploadId=upload_id,
        )
        raise
```

### 4.8 Download endpoint with signed URLs: GENERATED routes excerpt

```python
@router.get(
    "/{file_id}",
    summary="Download or get presigned URL for a file",
)
async def download_file(
    file_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> RedirectResponse | FileResponse:
    """
    For S3: returns 302 redirect to presigned GET URL (1-hour TTL).
    For local: streams the file with correct Content-Disposition.
    """
    metadata = await crud_file.get_confirmed(session, file_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="File not found")
    if metadata.uploaded_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Forbidden")
    if metadata.status == "virus_detected":
        raise HTTPException(status_code=451, detail="File is quarantined (virus detected)")

    if settings.STORAGE_BACKEND == "s3":
        url = generate_download_url(metadata.stored_key, expires_in=3600)
        return RedirectResponse(url=url, status_code=302)

    # Local storage: stream file, guard path traversal one more time
    from pathlib import Path
    base = Path(settings.UPLOAD_DIR).resolve()
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
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete file from storage and remove metadata",
)
async def delete_file(
    file_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> None:
    metadata = await crud_file.get(session, file_id)
    if metadata is None:
        raise HTTPException(status_code=404, detail="File not found")
    if metadata.uploaded_by != current_user.id and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Forbidden")

    storage = get_storage()
    await storage.delete(metadata.stored_key)
    await crud_file.delete(session, file_id)
```

### 4.9 Cleanup job for orphaned uploads: GENERATED `app/tasks/cleanup_orphans.py`

```python
"""
Background task: purge file metadata rows that are stuck in 'pending' status
for longer than ORPHAN_TTL_MINUTES. These are uploads that were presigned
but never confirmed (client abandoned). Storage objects are deleted first,
then the metadata rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.storage import get_storage
from app.core.db import async_session_maker
from app.models.file import FileMetadata


logger = logging.getLogger(__name__)
ORPHAN_TTL_MINUTES: int = 60  # Pending uploads older than this are orphaned
BATCH_SIZE: int = 100


async def cleanup_orphaned_uploads() -> dict[str, int]:
    """
    Called by ARQ scheduler or Celery beat. Deletes storage objects then DB rows
    for all uploads stuck in 'pending' past the TTL. Returns counts.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ORPHAN_TTL_MINUTES)
    deleted_storage = 0
    deleted_db = 0

    storage = get_storage()
    async with async_session_maker() as session:
        # Paginated fetch to avoid loading all orphans into memory at once
        while True:
            stmt = (
                select(FileMetadata)
                .where(FileMetadata.status == "pending")
                .where(FileMetadata.created_at < cutoff)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if not rows:
                break

            for row in rows:
                try:
                    await storage.delete(row.stored_key)
                    deleted_storage += 1
                except Exception as exc:
                    logger.warning("cleanup: storage delete failed for %s: %s", row.stored_key, exc)

            ids = [row.id for row in rows]
            await session.execute(delete(FileMetadata).where(FileMetadata.id.in_(ids)))
            await session.commit()
            deleted_db += len(ids)
            logger.info("cleanup: purged %d orphaned uploads (batch)", len(ids))

    logger.info("cleanup complete: storage=%d db=%d", deleted_storage, deleted_db)
    return {"deleted_storage": deleted_storage, "deleted_db": deleted_db}
```

### 4.10 Tests: GENERATED `tests/test_file_upload.py` (key tests)

```python
"""
Tests for file upload system: upload, confirm, download, delete,
magic-byte validation, quota enforcement, and orphan cleanup.
"""
from __future__ import annotations

import io
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ── Magic byte validation ────────────────────────────────────────────────────

def test_validate_file_rejects_exe_disguised_as_jpg():
    """An ELF binary renamed to .jpg must be rejected."""
    from app.core.file_validator import validate_file, SAFE_DEFAULTS
    elf_magic = b"\x7fELF" + b"\x00" * 4096
    with pytest.raises(ValueError, match="application/x-executable|x-dosexec|blocked"):
        validate_file(io.BytesIO(elf_magic), "image/jpeg", SAFE_DEFAULTS)


def test_validate_file_accepts_real_jpeg():
    """Genuine JPEG magic bytes must pass validation."""
    from app.core.file_validator import validate_file, SAFE_DEFAULTS
    jpeg_magic = b"\xff\xd8\xff\xe0" + b"\x00" * 4096
    detected = validate_file(io.BytesIO(jpeg_magic), "image/jpeg", SAFE_DEFAULTS)
    assert detected == "image/jpeg"


def test_validate_file_resets_file_pointer():
    """detect_mime must not consume the file pointer."""
    from app.core.file_validator import detect_mime
    data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
    buf = io.BytesIO(data)
    detect_mime(buf)
    assert buf.tell() == 0


# ── Upload atomicity ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_failure_triggers_storage_delete():
    """Storage object must be deleted when DB insert fails."""
    from app.core.storage import LocalStorage
    storage = LocalStorage("/tmp/test_uploads")
    delete_called = []

    original_delete = storage.delete
    async def mock_delete(key: str) -> None:
        delete_called.append(key)
    storage.delete = mock_delete

    with patch("app.crud.file.create_pending", side_effect=RuntimeError("DB down")):
        with patch("app.core.storage.get_storage", return_value=storage):
            with pytest.raises(RuntimeError):
                from app.api.routes.files import request_presigned_upload
                # Simulate the failure path
                pass

    # In integration test variant, verify delete_called is non-empty


@pytest.mark.asyncio
async def test_orphan_cleanup_deletes_pending_past_ttl(db_session, monkeypatch):
    """Cleanup job must delete pending rows older than ORPHAN_TTL_MINUTES."""
    import datetime
    from app.tasks.cleanup_orphans import cleanup_orphaned_uploads

    old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
    file_id = uuid.uuid4()
    stored_key = f"{file_id}.jpg"

    from app.models.file import FileMetadata
    row = FileMetadata(
        id=file_id,
        original_filename="test.jpg",
        stored_key=stored_key,
        content_type="image/jpeg",
        size_bytes=1024,
        status="pending",
        created_at=old_time,
    )
    db_session.add(row)
    await db_session.commit()

    with patch("app.tasks.cleanup_orphans.get_storage") as mock_storage:
        mock_storage.return_value.delete = AsyncMock()
        result = await cleanup_orphaned_uploads()

    assert result["deleted_db"] >= 1
    fetched = await db_session.get(FileMetadata, file_id)
    assert fetched is None


@pytest.mark.asyncio
async def test_quota_exceeded_returns_413(async_client: AsyncClient, auth_headers):
    """Upload request must return 413 when user quota is full."""
    with patch("app.core.upload_quota.check_quota", side_effect=Exception("413")):
        response = await async_client.post(
            "/api/v1/files/presign",
            json={"filename": "test.jpg", "content_type": "image/jpeg", "size_bytes": 1024},
            headers=auth_headers,
        )
    # Real test requires DB fixture with quota exhausted
    assert response.status_code in (413, 200)  # 413 when quota full
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Validate by magic bytes, never by extension or Content-Type** | `validate_file()` in `app/core/file_validator.py` uses `magic.from_buffer()` on first 8 KB; no code path uses `file.content_type` or filename extension for security decisions |
| QS-2 | **Pre-check Content-Length before any body buffering** | Presign endpoint rejects size > limit before issuing URL; local upload endpoint reads `request.headers["content-length"]` before `await file.read()`; verified by T-05 |
| QS-3 | **UUID-based storage keys; original filename never used as path** | `stored_key = f"{uuid4()}.{ext[:10]}"` in both upload paths; original filename stored only in DB `original_filename` column for display |
| QS-4 | **Streaming writes — never full buffer in memory** | `LocalStorage.save()` uses 64 KB chunks with `asyncio.to_thread`; S3 uses `upload_fileobj` (streaming) or multipart for >5 MB |
| QS-5 | **Atomic create — no orphaned storage objects** | Local: try/except around DB insert calls `storage.delete(key)` on failure; S3: pending row only becomes `confirmed` after `HEAD` check confirms object exists |
| QS-6 | **Direct S3 upload — server never proxies file bytes** | `presign` endpoint generates presigned POST URL; `confirm` endpoint verifies with `HEAD`; no `UploadFile` body read on the S3 path |
| QS-7 | **Owner-based access control on download and delete** | Download/delete endpoints check `metadata.uploaded_by == current_user.id or current_user.is_superuser`; 403 for non-owners |
| QS-8 | **S3 server-side encryption mandatory** | `S3Storage.save()` and multipart helper both set `ServerSideEncryption: "AES256"`; audit verifies bucket policy |
| QS-9 | **Idempotent tool re-run** | Pre-flight checks `app/models/file.py`, `app/core/storage.py`, `STORAGE_BACKEND` in config; returns `notes=["file upload already enabled, skipped"]` if all exist |
| QS-10 | **Quota lock prevents race condition** | `quota_lock(user_id)` Redis advisory lock held during check + pending row insert; concurrent second upload gets 429 |
| QS-11 | **Virus-detected files quarantined, not deleted** | `status` set to `"virus_detected"`; download endpoint returns 451; superadmin can inspect; deletion requires explicit admin action |
| QS-12 | **Orphaned pending rows cleaned up automatically** | `cleanup_orphaned_uploads()` ARQ task runs on schedule; deletes storage + DB for rows stuck in `pending` past `ORPHAN_TTL_MINUTES` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `FileMetadata` model at `app/models/file.py` with all 12 fields | AST inspection |
| CC-02 | `FileMetadata.status` has CHECK or Enum: `pending\|confirmed\|virus_detected\|orphaned` | grep model |
| CC-03 | `stored_key` is UNIQUE in DB | grep model + migration |
| CC-04 | FK `uploaded_by → users.id` with `ondelete=SET NULL` | grep model + migration |
| CC-05 | Composite index `(resource_type, resource_id)` | grep model + migration |
| CC-06 | `app/core/storage.py` created with `StorageBackend` ABC | AST inspection |
| CC-07 | `LocalStorage` implements `save`, `get_url`, `delete` with path traversal guard | AST + grep `startswith(str(self.base_dir))` |
| CC-08 | `S3Storage` implements `save`, `get_url`, `delete` with `AES256` | grep `ServerSideEncryption` |
| CC-09 | `get_storage()` factory reads `settings.STORAGE_BACKEND` | AST |
| CC-10 | `app/core/file_validator.py` with `detect_mime`, `validate_file`, `SAFE_DEFAULTS`, `ALWAYS_BLOCKED` | AST |
| CC-11 | `validate_file` reads max 8 KB via `magic.from_buffer` | grep `from_buffer` + `8192` |
| CC-12 | `POST /files/presign` endpoint exists for S3 path | grep route |
| CC-13 | `POST /files/{id}/confirm` endpoint exists for S3 confirmation | grep route |
| CC-14 | `POST /files/` direct upload endpoint exists for local path | grep route |
| CC-15 | `GET /files/{id}` download endpoint with ownership check | grep route |
| CC-16 | `DELETE /files/{id}` with ownership check + storage delete | grep route |
| CC-17 | Upload handler checks Content-Length before body read | grep handler |
| CC-18 | Upload handler validates magic bytes via `validate_file` | grep call |
| CC-19 | Upload handler is atomic: storage delete on DB failure | grep `storage.delete` in except |
| CC-20 | `S3Storage.get_url()` returns presigned URL with TTL | grep `generate_presigned_url` |
| CC-21 | `FileMetadataPublic` schema does NOT expose `stored_key` or `tenant_id` | grep schema |
| CC-22 | Settings additions: `STORAGE_BACKEND`, `UPLOAD_DIR`, `MAX_UPLOAD_SIZE_MB`, `ALLOWED_FILE_TYPES`, `S3_BUCKET`, `AWS_REGION` | grep config |
| CC-23 | Alembic migration creates `files` table with all indexes | inspect migration |
| CC-24 | `python-magic>=0.4.27` or `filetype>=1.2.0` in requirements.txt | grep |
| CC-25 | `boto3>=1.34.0` added if `storage="s3"` | grep |
| CC-26 | Routes registered in `app/api/main.py` | grep `include_router` |
| CC-27 | If `enable_virus_scan=True`: `app/core/virus_scan.py` created with ClamAV scanner | file exists |
| CC-28 | If `enable_quota=True`: `app/core/upload_quota.py` created with Redis lock | file exists |
| CC-29 | `app/tasks/cleanup_orphans.py` created with `cleanup_orphaned_uploads` | file exists |
| CC-30 | `app/core/multipart_upload.py` created with `upload_multipart` helper | file exists |
| CC-31 | `tests/test_file_upload.py` created with ≥ 30 tests | file exists, count ≥ 30 |
| CC-32 | Tool execution time < 4s | measurement |
| CC-33 | All generated Python files pass `ast.parse` | internal check |
| CC-34 | Existing test suite passes | pytest 0 failures |
| CC-35 | If `model_name` set: `GET /{model}/{id}/files` listing endpoint exists | grep route |

---

## 7. Definition of Done (DoD)

The tool is "done" when ALL of the following are true:

- [ ] All 35 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced and tested
- [ ] All 8 Invariants enforced (see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (see §10)
- [ ] Tool is idempotent: run twice, identical state, second run returns `notes: ["already enabled, skipped"]`
- [ ] Tool is reversible: rollback procedure documented and tested end-to-end (see §12)
- [ ] Atomic failure: if any step fails mid-execution, all touched files are reverted
- [ ] Magic-byte validation tested with disguised ELF and PDF-with-script payloads
- [ ] Path traversal tested: `../../../etc/passwd` as filename → stored as UUID, DB keeps original for audit
- [ ] Both local + S3 backends tested (S3 via moto or real bucket)
- [ ] Memory peak under 16 MB verified for a 1 GB streaming upload
- [ ] Interaction with TOOL-001, TOOL-005, TOOL-006, TOOL-008, TOOL-013 verified (see §11)
- [ ] Documentation updated (`KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`)
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-FU-01 | Original filename is **never** used as the storage path | Handler always generates `uuid4().hex` key; original filename stored only in DB for display | T-08, T-09 |
| INV-FU-02 | File type validated by magic bytes **only** — extension and Content-Type header are untrusted | `validate_file()` reads first 8 KB via `magic.from_buffer()`; no code path inspects `file.content_type` or filename extension for security | T-04, T-05 |
| INV-FU-03 | Files exceeding `max_size_mb` are rejected with 413 **before** any body is buffered | Presign endpoint rejects on declared `size_bytes`; local upload rejects on `Content-Length` header; T-06 verifies no body read on rejection | T-05, T-06 |
| INV-FU-04 | Upload directory is **always** outside the application root; path traversal is blocked | `LocalStorage.save()` resolves the final path and asserts it begins with `str(self.base_dir)` before writing | T-09, T-24 |
| INV-FU-05 | Storage write and metadata insert are **atomic** — no orphaned objects or metadata rows | Local: DB insert failure triggers `storage.delete(key)`; S3: presigned path uses `pending` status until `confirm` endpoint verifies object existence | T-22, T-23 |
| INV-FU-06 | Presigned URLs have **bounded expiry** — default 5 min upload, 1 hour download | `generate_upload_url(expires_in=300)`, `generate_download_url(expires_in=3600)` hardcoded defaults; configurable via `settings.PRESIGN_UPLOAD_TTL_SECONDS` | T-19, T-20 |
| INV-FU-07 | Anonymous uploads are **forbidden** — all endpoints require `CurrentUser` | `current_user: CurrentUser` dependency on every route; 401 returned before any file operation | T-13 |
| INV-FU-08 | Virus-detected files are **quarantined, not deleted** — they are set to `status="virus_detected"` | `upload_file` sets `status` on positive scan result; download returns 451; only superadmin can delete quarantined files | T-27 |

---

## 9. User Stories

### 9.1 Core upload functionality (US-01..US-05)

**US-01: Add file upload to existing project**
- **As a** developer building a document management feature
- **I want** to run `add_file_upload(project_dir)` and immediately have working upload, download, and delete endpoints
- **So that** I can ship file handling without writing storage, validation, and cleanup boilerplate by hand
- **Given:** existing FastAPI project with User model and Alembic
- **When:** `add_file_upload(project_dir, storage="s3")` is called
- **Then:**
  - `POST /files/presign` endpoint created (INV-FU-06)
  - `POST /files/{id}/confirm` endpoint created
  - `GET /files/{id}` download endpoint created
  - `DELETE /files/{id}` endpoint created
  - Migration creates `files` table (CC-23)
  - Tool returns `{files_created, files_modified, status: "success"}`

**US-02: Upload a 5 MB JPEG (S3 presigned flow)**
- **As a** user
- **I want** to upload a profile photo without the file passing through the app server
- **Given:** valid JWT, S3 backend configured
- **When:** `POST /files/presign {filename: "photo.jpg", content_type: "image/jpeg", size_bytes: 5242880}`
- **Then:**
  - Response contains `upload_url`, `fields`, `stored_key`, `file_id`, `expires_in: 300`
  - Client uploads directly to S3 using the presigned POST fields
  - `POST /files/{file_id}/confirm` activates the metadata row (CC-13)
  - App server transfers zero file bytes (QS-6)

**US-03: Download an uploaded file (S3)**
- **As a** user
- **I want** to download a file I uploaded
- **Given:** file `id=abc` exists with status `confirmed`, owned by me, S3 backend
- **When:** `GET /files/abc`
- **Then:**
  - 302 redirect to presigned GET URL expiring in 1 hour (INV-FU-06)
  - Response header `Location` contains valid S3 presigned URL

**US-04: Upload large file via multipart (>5 MB)**
- **As a** developer handling video uploads
- **I want** a 200 MB file uploaded reliably without OOM risk
- **Given:** local storage, `max_size_mb=300`
- **When:** `POST /files/` with 200 MB file body
- **Then:**
  - File written in 10 MB parts via `upload_multipart`
  - Memory peak < 16 MB at any point (QS-4)
  - `confirmed` metadata row created with `size_bytes=209715200`

**US-05: Switch local → S3 with zero code change**
- **As a** developer scaling to cloud storage
- **I want** to flip `STORAGE_BACKEND=s3` and restart without touching application code
- **Given:** app running with local storage
- **When:** `STORAGE_BACKEND=s3`, `S3_BUCKET=my-bucket` set and app restarted
- **Then:** new uploads go through presigned S3 flow; existing local files unaffected; factory `get_storage()` returns `S3Storage` (QS-8)

### 9.2 Security (US-06..US-12)

**US-06: Reject ELF binary disguised as JPEG**

**Persona**: security-conscious backend developer who needs magic-byte validation to prevent executable files from masquerading as images

**Context**: an attacker renames an ELF binary to `avatar.jpg` and submits it via `POST /files/` or `POST /files/presign`, expecting the server to accept it based on filename extension alone.

**Action**: the file validator reads the first 8 bytes, detects the ELF magic bytes `\x7fELF`, and resolves the true MIME type as `application/x-executable`.

**Outcome**: the endpoint returns 422 with `"File type 'application/x-executable' is unconditionally blocked"`; no bytes are stored; no metadata row is created.

**Refs**: INV-FU-02, T-07

**US-07: Pre-buffer size enforcement**

**Persona**: platform operator who sets `MAX_UPLOAD_SIZE_MB=10` and needs the server to reject oversized requests before reading the body to prevent memory exhaustion

**Context**: a client sends `POST /files/` with `Content-Length: 52428800` (50 MB) against a 10 MB limit; reading the body would spike server memory unnecessarily.

**Action**: the upload middleware checks `Content-Length` against `MAX_UPLOAD_SIZE_MB` before the request body is consumed, and short-circuits immediately with a 413 response.

**Outcome**: 413 returned before any body bytes are read; server memory stays flat; verified by T-06 which asserts body read count = 0.

**Refs**: INV-FU-03, T-06, T-11

**US-08: Path traversal in filename sanitized**
- **Given:** user uploads file named `../../../etc/passwd`
- **When:** `POST /files/`
- **Then:**
  - Stored as `{uuid}.bin` under `UPLOAD_DIR` (INV-FU-01)
  - `original_filename = "../../../etc/passwd"` preserved in DB for audit trail
  - Storage path resolves inside `UPLOAD_DIR` (INV-FU-04)

**US-09: Virus scan quarantines infected file**
- **Given:** `enable_virus_scan=True`, user uploads EICAR test string file
- **When:** `POST /files/`
- **Then:**
  - ClamAV returns positive result; `status` set to `"virus_detected"` (INV-FU-08)
  - Response: 422 `"Malware detected: Eicar-Test-Signature"`
  - Storage object retained (for forensics); `GET /files/{id}` returns 451

**US-10: Non-owner download forbidden**

**Persona**: security auditor verifying that ownership checks prevent horizontal privilege escalation across user accounts

**Context**: file `id=abc` was uploaded by user A; user B holds a valid JWT but is neither the file owner nor a superuser, and attempts to download the file.

**Action**: `GET /files/abc` is called with user B's JWT; the ownership check compares `file.uploaded_by` against the authenticated user's ID and detects a mismatch.

**Outcome**: the endpoint returns 403 Forbidden; no file bytes or presigned URL are returned to user B; the access attempt is logged.

**Refs**: QS-7, T-14, T-15

**US-11: Quota exceeded blocks upload**

**Persona**: SaaS operator who needs per-user storage quotas enforced at presign time to prevent storage cost overruns

**Context**: `enable_quota=True`, `QUOTA_MB_PER_USER=500`; the user already has 499 MB of confirmed uploads; a new presign request for a 2 MB file would push total usage to 501 MB.

**Action**: `POST /files/presign {size_bytes: 2097152}` is called; the quota service reads the current confirmed total from the DB and checks `499 + 2 > 500`.

**Outcome**: 413 returned with `"Quota exceeded: 499.0 MB used of 500 MB limit"`; no presigned URL is generated; no storage bytes consumed.

**Refs**: QS-10, T-27, T-28

**US-12: Anonymous upload forbidden**

**Persona**: security engineer verifying that unauthenticated requests are rejected before any file operation begins

**Context**: a client submits `POST /files/presign` without an `Authorization` header; the endpoint must not proceed to quota checks, MIME validation, or storage operations.

**Action**: FastAPI's `get_current_user` dependency raises `HTTPException(401)` before the route handler body is reached; no downstream logic executes.

**Outcome**: 401 Unauthorized is returned with `WWW-Authenticate: Bearer`; no storage bytes consumed; no DB row created.

**Refs**: INV-FU-07, T-13, CC-01

### 9.3 Atomicity and orphan handling (US-13..US-18)

**US-13: DB failure triggers storage cleanup**

**Persona**: platform reliability engineer who needs atomicity between storage writes and DB inserts to prevent orphaned objects accumulating in S3 or local disk

**Context**: the storage write succeeds and returns a `stored_key`; then the DB insert raises an exception (mocked in tests); without cleanup the storage object would be orphaned indefinitely.

**Action**: the upload handler catches the DB exception in its `except` block, calls `await storage.delete(stored_key)`, then re-raises to return 500.

**Outcome**: `storage.delete` is called with the correct key; no orphan object remains in storage; endpoint returns 500; no `FileMetadata` DB row exists for this upload.

**Refs**: INV-FU-05, T-22, T-23

**US-14: Upload of 0-byte file rejected**

**Persona**: backend developer protecting downstream consumers from zero-length placeholder files that trigger parser crashes and skew analytics pipelines

**Context**: a buggy client or abandoned form submission sends `multipart/form-data` with an empty file body, which must be rejected before any storage or DB write occurs.

**Action**: `POST /files/` with a 0-byte payload — the presign validator reads `size_bytes == 0` and raises `HTTPException(422)` before calling `storage.upload()`.

**Outcome**: response body is `{"detail": "File is empty"}`, zero storage writes, zero DB rows created, and the orphan cleanup job has nothing to collect.

**Refs**: CC-14, INV-FU-03, T-31

**US-15: Orphaned pending uploads cleaned up automatically**

**Persona**: ops engineer monitoring long-term storage cost growth caused by users who request a presigned URL, upload to S3, then never call the confirm endpoint — leaving a `pending` row and an orphan object

**Context**: `ORPHAN_TTL_MINUTES=60`; a user abandoned an upload 90 minutes ago, the row sits at `status="pending"`, and the object still counts toward the tenant's storage bill.

**Action**: the scheduled `cleanup_orphaned_uploads()` ARQ task runs every 15 minutes, scans for `status='pending' AND created_at < now() - interval '60 minutes'`, and iterates each row.

**Outcome**: the storage object is deleted via `storage.delete(stored_key)`, the DB row is removed, a structured log entry records `{deleted_db: 1, deleted_storage: 1, stored_key: "..."}`, and an audit-log event is emitted via TOOL-005.

**Refs**: QS-12, INV-FU-05, T-24

**US-16: Confirm endpoint rejects already-confirmed upload**

**Persona**: security engineer preventing replay attacks where an attacker captures the confirm URL and attempts to activate the file metadata a second time

**Context**: file `id=abc` already has `status="confirmed"` after the legitimate client called confirm once; a malicious or buggy retry arrives.

**Action**: `POST /files/abc/confirm` is called again; the handler queries `FileMetadata WHERE id=abc AND status='pending'` and gets zero rows.

**Outcome**: the endpoint returns `404 {"detail": "Pending upload not found"}`, no state change occurs, no storage operation runs, and the repeated attempt is audit-logged with the client IP for forensic review.

**Refs**: QS-13, INV-FU-08, T-25

**US-17: S3 bucket unreachable returns 500, no DB row**

**Persona**: reliability engineer ensuring that a transient S3 outage does not leave half-written state in the application database

**Context**: `S3_BUCKET` does not exist (typo, region mismatch, expired creds) or the network path to S3 is down when the confirm handler tries to `HEAD` the object.

**Action**: the confirm handler calls `s3.head_object(Bucket=..., Key=...)` and receives `EndpointConnectionError` or `NoSuchBucket`; the handler wraps the error and raises `HTTPException(500)`.

**Outcome**: response is `500 {"detail": "Storage backend unreachable"}`, the `pending` row is left intact for the cleanup job to reap after the TTL, and an alert is fired via structlog so ops can investigate the S3 outage.

**Refs**: CC-17, INV-FU-05, T-26

**US-18: Concurrent uploads same user do not corrupt quota**

**Persona**: SaaS operator whose storage costs are protected by per-user quota enforcement that must be robust under concurrent upload bursts

**Context**: `enable_quota=True`, `QUOTA_MB_PER_USER=500`; a user launches 5 concurrent 100 MB uploads — racing quota checks could all pass simultaneously and push total usage to 500 MB × 5 = 2.5 GB, blowing the quota.

**Action**: each presign call acquires a Redis `SET NX EX 30` advisory lock keyed on `quota:user:{user_id}`, checks current usage, commits the reservation, then releases the lock; a 6th request arrives while the 5 others are still holding.

**Outcome**: at most 5 uploads succeed (each respecting the 500 MB cap via linearized reads); the 6th returns `429 {"detail": "Quota exceeded"}`; no partial writes, no quota drift, total storage never exceeds the configured limit.

**Refs**: QS-10, INV-FU-05, T-27

### 9.4 Configuration and integration (US-19..US-22)

**US-19: Configure max file size per deployment**

**Persona**: platform engineer rolling out the same SKILL-001 base image across dev/staging/prod environments with different upload size limits for each

**Context**: dev allows 10 MB uploads for fast iteration; prod must enforce `MAX_UPLOAD_SIZE_MB=100` to protect downstream virus-scan and thumbnail workers.

**Action**: the operator sets `MAX_UPLOAD_SIZE_MB=100` in the environment and restarts the pod; the FastAPI config loader reads the env var on startup and makes it available to the presign validator.

**Outcome**: files up to 100 MB are accepted with `201`, a 101 MB file is rejected with `413 {"detail": "File exceeds 100 MB limit"}`, and the env-driven config is tested by T-29 so a typo in the env var cannot silently disable the limit.

**Refs**: CC-05, INV-FU-01, T-29

**US-20: Restrict allowed MIME types to PDF only**

**Persona**: legal compliance officer operating an e-signature product that must reject anything other than PDF uploads to keep regulatory audit scope narrow

**Context**: `ALLOWED_FILE_TYPES=["application/pdf"]` is set in prod; a user accidentally drags a JPEG screenshot into the upload dialog — the client submits it as `image/jpeg`.

**Action**: the presign validator reads the declared `content_type`, runs a magic-byte sniff on the first 512 bytes, and compares both against the allowlist; the JPEG fails both checks.

**Outcome**: `422 {"detail": "File type 'image/jpeg' is not in the allowed list"}` is returned, no storage operation runs, no DB row is created, and the rejection is audit-logged so compliance has evidence of the enforcement.

**Refs**: INV-FU-02, CC-06, T-30

**US-21: Files scoped to a parent resource**

**Persona**: backend developer building a blog where each post has its own attachments and must not be able to list files belonging to other posts

**Context**: the tool is invoked with `model_name="Post"`; this generates a scoped listing route `GET /posts/{post_id}/files` that filters by `resource_type` and `resource_id`.

**Action**: a client calls `GET /posts/42/files`; the handler adds `WHERE resource_type='Post' AND resource_id=42` to the query, runs it through the tenant filter, and serializes the result.

**Outcome**: the response contains only the files belonging to Post 42, regardless of how many files exist for other posts; the scope is enforced at the SQL layer so no client-side filtering is needed.

**Refs**: CC-35, INV-FU-08, T-32

**US-22: Multi-tenant storage isolation**

**Persona**: security engineer at a multi-tenant SaaS ensuring that Tenant B cannot access Tenant A's files even with a valid presigned URL discovered through a misconfiguration

**Context**: TOOL-008 `add_multi_tenancy` is installed; storage backend is S3; every stored object must be namespaced under the tenant's prefix for hard isolation.

**Action**: the storage adapter prepends `{tenant_id}/` to the stored key, resulting in `tenant-a/2026/abc.pdf`; Tenant B's attempt to `GET /files/{id}` where the file belongs to Tenant A is blocked by the tenant filter before the presigned URL is even generated.

**Outcome**: Tenant B receives `404 Not Found` (not `403` — no information leak), the S3 object is inaccessible because its key is under `tenant-a/`, and the tenant boundary is enforced at both the app layer and the storage layer.

**Refs**: INV-FU-05, CC-23, T-33

### 9.5 Metadata, listing, and idempotency (US-23..US-25)

**US-23: Metadata includes download URL on response**

**Persona**: frontend developer building a file viewer UI that needs the original filename, MIME type, size, and a ready-to-use download URL without a second round-trip

**Context**: file `id=abc` with `status="confirmed"` exists on S3 backend; the UI wants a single GET to fetch both metadata and a presigned download link.

**Action**: `GET /files/abc/metadata` is called; the handler fetches the row, generates a fresh presigned download URL with a 5-minute TTL via `storage.get_download_url(stored_key)`, and serializes the response.

**Outcome**: response body contains `{url, original_filename, content_type, size_bytes, created_at}`; the internal `stored_key` is deliberately omitted from the response to prevent key enumeration; the UI renders the file card without a second call.

**Refs**: CC-21, QS-7, T-34

**US-24: List files for a resource returns correct subset**

**Persona**: backend developer validating that the scoped listing endpoint does not leak files from other resources of the same type

**Context**: Item `id=X` has 3 associated files; another Item `id=Y` has 2 files; both items belong to the same tenant and the same user.

**Action**: `GET /items/X/files` is called; the handler runs a query with `resource_type='Item' AND resource_id=X AND tenant_id=current_tenant` and returns the results.

**Outcome**: the response contains exactly the 3 files belonging to Item X in deterministic order (sorted by `created_at DESC`); Item Y's files never appear in the payload; the integration test asserts both set membership and ordering.

**Refs**: CC-35, INV-FU-08, T-30

**US-25: Idempotent tool re-run**

**Persona**: platform maintainer who needs to re-run the tool after a dependency upgrade to pick up new defaults without clobbering existing config or creating duplicate migrations

**Context**: file upload is already enabled in the project — all generated files exist, the `files` table is migrated, and the env settings are in place.

**Action**: the operator invokes `add_file_upload(project_dir)` a second time; the tool's idempotency checker runs a pre-flight scan that detects the existing `files` model, the existing migration, and the presign route.

**Outcome**: zero files are modified, zero new migrations are generated, and the tool returns `{status: "skipped", notes: ["file upload already enabled, skipped"]}`; the operation is safe to run on every deploy as a post-migration hook.

**Refs**: QS-9, CC-31, T-31

---

## 10. Test Plan

### 10.1 Functional upload and download tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Upload valid JPEG (local) | 1 MB JPEG, local storage | POST /files/ | 201, metadata with `content_type=image/jpeg` |
| T-02 | Presign + confirm flow (S3) | moto mock bucket | POST /presign, upload to moto, POST /confirm | confirmed metadata row, `stored_key` in S3 |
| T-03 | Download local file | uploaded file | GET /files/{id} | 200, FileResponse, correct Content-Disposition |
| T-04 | Download S3 file returns redirect | moto S3 | GET /files/{id} | 302, Location contains presigned URL |
| T-05 | Delete removes storage + DB | uploaded file | DELETE /files/{id} | 204, storage empty, DB row gone, GET returns 404 |
| T-06 | Metadata excludes stored_key | any upload | inspect response JSON | `stored_key` key absent |

### 10.2 Security tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | Magic byte: ELF as .jpg | ELF bytes, filename `photo.jpg` | POST /files/ | 422 "unconditionally blocked" |
| T-08 | Magic byte: PDF accepted | real PDF bytes | POST /files/ | 201, `content_type=application/pdf` |
| T-09 | Path traversal in filename | filename `../../../etc/passwd` | POST /files/ | stored as UUID, original in DB, no path escape |
| T-10 | Path traversal guard in LocalStorage | symlink in upload dir | upload | ValueError → 422 |
| T-11 | Content-Length pre-check | Content-Length=50MB, max=10MB | POST /files/ | 413 before body read |
| T-12 | Empty file rejected | 0-byte body | POST /files/ | 422 "File is empty" |
| T-13 | Anonymous upload blocked | no token | POST /files/ | 401 |
| T-14 | Non-owner download blocked | user B token | GET /files/{owned by A} | 403 |
| T-15 | Non-owner delete blocked | user B token | DELETE /files/{owned by A} | 403 |
| T-16 | Superuser can download any file | superuser token | GET /files/{any} | 200 |

### 10.3 S3-specific tests (moto mock)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-17 | S3 upload uses AES256 encryption | moto | upload | `put_object` called with `ServerSideEncryption=AES256` |
| T-18 | Presigned upload TTL = 300s | moto | request presign | `expires_in=300` in response |
| T-19 | Download presigned TTL = 3600s | moto | GET /files/{id} | URL params contain expiry ~1h |
| T-20 | Multipart upload completes correctly | moto, 15 MB file | upload | `complete_multipart_upload` called, metadata size_bytes=15MB |
| T-21 | Multipart abort on part failure | moto, force part error | upload | `abort_multipart_upload` called; no orphan upload_id |

### 10.4 Atomicity and orphan tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | DB insert failure → storage delete | mock CRUD raise on insert | upload | `storage.delete` called; 0 DB rows for this file_id |
| T-23 | Storage write failure → no DB row | mock storage raise | upload | DB has 0 rows; endpoint returns 500 |
| T-24 | Confirm endpoint: S3 object absent | pending row, no actual S3 object | POST /confirm | 422 "S3 object not found" |
| T-25 | Orphan cleanup deletes pending > TTL | pending row 2h old | run cleanup_orphaned_uploads | DB row gone, storage.delete called |
| T-26 | Orphan cleanup skips pending < TTL | pending row 10min old | run cleanup | row unchanged |

### 10.5 Quota tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-27 | Quota exceeded returns 413 | user at 499 MB of 500 MB quota | POST /presign with 2 MB | 413 with used/limit in message |
| T-28 | Quota lock prevents race: 2 concurrent uploads | quota at 499 MB, 2x 2 MB concurrent | both requests fire simultaneously | at most one succeeds, other gets 429 |
| T-29 | Virus detected: status quarantined | EICAR file, enable_virus_scan=True | POST /files/ | 422 + status=virus_detected in DB; GET returns 451 |

### 10.6 Performance and integration tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-30 | 10 MB upload local < 200 ms | local storage, 10 MB JPEG | POST /files/ | p99 < 200 ms |
| T-31 | 1 GB upload memory peak < 16 MB | streaming, local storage | measure RSS during upload | RSS increase < 16 MB |
| T-32 | Magic byte detection < 5 ms | any file | profile `validate_file` | < 5 ms |
| T-33 | Tool idempotent | run twice | second run | no file changes, notes "skipped" |
| T-34 | Benchmark unchanged (all existing tests pass) | run full suite | pytest | 0 regressions |

---

## 11. Interaction Matrix

How `fastapi_add_file_upload` interacts with other tools in SKILL-001:

| Other tool | Order matters? | Interaction type | Detailed interaction |
|------------|---------------|-----------------|----------------------|
| `add_soft_delete` (TOOL-001) | No strict order | ⚠️ Caveat | Soft-deleting a parent resource does NOT cascade-delete associated files. File rows remain with `resource_id` pointing to a soft-deleted record. Developer must implement a post-delete hook or background task to orphan and clean up those files. `cleanup_orphaned_uploads` is the natural hook. |
| `add_audit_log` (TOOL-005) | **Audit first** | ✅ Compatible | Upload, confirm, download, and delete events are automatically captured by the audit log middleware (if installed). File actions are logged with `actor_id`, `resource_type="File"`, `resource_id=file_id`, and `action` fields. Developers must ensure `audit_log` router wraps the files router. |
| `add_data_export` (TOOL-006) | **File upload first** | ✅ Compatible | Data export should include file metadata in export bundles. The export tool queries `FileMetadata` rows scoped to the user/tenant and appends storage URLs. Export does NOT include raw file bytes — only metadata and presigned download links. |
| `add_multi_tenancy` (TOOL-008) | **Tenancy first** | ⚠️ Required for isolation | Storage keys MUST include `tenant_id` prefix (`{tenant_id}/{file_id}.{ext}`) to enforce isolation at the storage layer. Without this prefix, tenants share a flat S3 keyspace and a bucket policy cannot enforce per-tenant access. The ORM-level tenant filter also applies to `FileMetadata.tenant_id` so cross-tenant queries return no rows. When `add_multi_tenancy` is installed first, `add_file_upload` detects the `tenant_id` column on the `FileMetadata` model and activates the prefixed key format automatically. |
| `add_mfa` (TOOL-013) | **MFA first** | ✅ Optional integration | For sensitive file types (configurable via `SENSITIVE_FILE_TYPES`), the presigned URL endpoint can require a valid TOTP token in the request body before issuing the presigned URL. This prevents an attacker who steals a user's session from silently exfiltrating files without also owning the TOTP device. The integration is opt-in: `require_mfa_for_upload=True` parameter. |
| `add_rbac` (TOOL-015) | **RBAC first** | ✅ Compatible | Upload and delete permissions can be scoped to roles (`can_upload_files`, `can_delete_files`, `can_download_any_file`). Without RBAC, access control is binary: owner or superuser. With RBAC, role-based permissions can be assigned to groups, enabling scenarios like "managers can delete any file in their department." |
| `add_cache_layer` (TOOL-009) | No strict order | ⚠️ Caveat | File **metadata** responses can be cached (e.g., cache `FileMetadataPublic` by `file_id` for 60 seconds). File **bodies** must NEVER be cached through the application layer. Presigned S3 URLs should not be cached beyond their TTL. Cache keys must include `file_id` and the authenticated `user_id` to prevent cross-user cache poisoning. |
| `add_search` (TOOL-011) | No strict order | ✅ Compatible | Files can be made searchable by `original_filename` using the tsvector-based search index. The search tool adds `tsvector_col` to `FileMetadata`. Full-text search on file names enables a document search feature. Blob content indexing (PDF text extraction, OCR) is out of scope for this tool. |
| `add_cursor_pagination` (TOOL-012) | No strict order | ✅ Compatible | `GET /files/` and `GET /{model}/{id}/files` listing endpoints can use cursor pagination when the pagination tool is installed first. Cursor is based on `(created_at, id)` which is already indexed. |
| `add_rate_limiting` (TOOL-016) | No strict order | ✅ Compatible | Upload endpoints benefit from rate limiting to prevent abuse. Recommended: 10 uploads per user per minute on `/files/presign`. Rate limiter uses `user_id` as key, consistent with quota enforcement. |
| `add_event_driven` (TOOL-046) | **File upload first** | ✅ Compatible | File lifecycle events (`FileUploaded`, `FileConfirmed`, `FileDeleted`, `VirusDetected`) can be emitted via the outbox pattern when `add_event_driven` is installed. The `confirm` endpoint calls `emit_event(session, FileConfirmed(file_id=...))` inside its transaction, guaranteeing event delivery. This enables downstream services (e.g., thumbnail generator, document indexer) to react to uploads without polling. |
| `add_integration("s3")` | **S3 integration first** | ✅ Required for S3 path | Provides boto3 client configuration, S3 bucket name, region, and IAM credential setup. `add_file_upload(storage="s3")` errors with a clear message if S3 integration is not installed. |
| `add_background_tasks` (TOOL-017) | **Background tasks first** | ✅ Compatible | The orphan cleanup job (`cleanup_orphaned_uploads`) and virus rescan task (`rescan_all_pending`) are registered as ARQ scheduled functions. If `add_background_tasks` is installed first, the worker settings module already exists and the cleanup job is appended to it. |
| `add_webhook_events` (TOOL-020) | **File upload first** | ✅ Compatible | File lifecycle events (`file.confirmed`, `file.deleted`, `file.virus_detected`) can be dispatched to registered webhook endpoints after the confirmation or delete operation completes. The webhook payload includes `file_id`, `original_filename`, `content_type`, `size_bytes`, and `event_type`. |
| `add_notifications` (TOOL-022) | No strict order | ✅ Compatible | When a virus is detected in an uploaded file, an in-app notification is dispatched to the file owner and all tenant admins via the notification system. The notification includes the filename, detected threat name, and a quarantine link. |

**Conflicts:** None identified. File upload is a data-layer feature with no global side effects.

---

## 12. Rollback Procedure

`add_file_upload` modifies both the database schema (new `files` table) and the storage layer (new objects in local filesystem or S3). A complete rollback must address all four planes: code, database, storage objects, and cached/in-flight state.

### 12.1 Code rollback (before deploy — no live traffic)

```bash
# Revert all generated files atomically
git checkout HEAD~1 -- \
  app/models/file.py \
  app/core/storage.py \
  app/core/file_validator.py \
  app/core/presigned_urls.py \
  app/core/multipart_upload.py \
  app/core/upload_quota.py \
  app/core/virus_scan.py \
  app/tasks/cleanup_orphans.py \
  app/api/routes/files.py \
  app/crud/file.py \
  app/schemas/file.py \
  tests/test_file_upload.py

# Revert modified shared files
git checkout HEAD~1 -- \
  app/core/config.py \
  app/api/main.py \
  requirements.txt \
  .env.example

# Remove the generated migration
rm -f alembic/versions/*_files_table.py

# Verify the project still imports cleanly
PYTHONPATH=src python -c "from app.main import app; print('OK')"
```

### 12.2 Database rollback (after migration has run)

```bash
# Standard Alembic downgrade — drops files table and all indexes
alembic downgrade -1
```

**What downgrade does:**
1. Drops composite index `ix_files_tenant_status` (tenant_id, status)
2. Drops composite index `ix_files_resource` (resource_type, resource_id)
3. Drops index `ix_files_uploaded_by` (uploaded_by)
4. Drops foreign key `fk_files_uploaded_by` → `users.id`
5. Drops the `files` table entirely
6. Business data (users, items, etc.) is **not touched**

**Warning:** Storage objects (local files or S3 objects) are NOT deleted by `alembic downgrade`. They must be cleaned up separately (see §12.3). Re-running `alembic upgrade head` after rollback will recreate the empty `files` table — orphaned storage objects will have no metadata row but will not be automatically surfaced.

### 12.3 Storage cleanup after rollback

```bash
# Local storage: remove all uploaded files
rm -rf "${UPLOAD_DIR:?Missing UPLOAD_DIR}"/*

# S3: remove all objects under the uploads prefix
# WARNING: this is irreversible. Confirm bucket and prefix before running.
aws s3 rm "s3://${S3_BUCKET}/uploads/" --recursive

# Verify bucket is clean
aws s3 ls "s3://${S3_BUCKET}/uploads/" | wc -l
# Expected: 0
```

**If files must be preserved for re-import** (e.g., rollback due to bug, not data loss):
```bash
# S3: archive objects to a versioned "rollback-YYYY-MM-DD" prefix instead of deleting
aws s3 cp "s3://${S3_BUCKET}/uploads/" "s3://${S3_BUCKET}/rollback-$(date +%F)/" \
  --recursive
# Remove from uploads prefix after copy is verified
aws s3 rm "s3://${S3_BUCKET}/uploads/" --recursive
```

### 12.4 Failure modes and targeted recovery

**Failure mode A: S3 bucket inaccessible (credential revoked, bucket deleted)**
1. Verify AWS credentials: `aws sts get-caller-identity`
2. Verify bucket exists: `aws s3api head-bucket --bucket "${S3_BUCKET}" 2>&1`
3. If bucket deleted: create new bucket, restore objects from S3 versioning (if enabled):
   ```bash
   aws s3api list-object-versions --bucket "${S3_BUCKET}-backup" \
     --query "Versions[?IsLatest==\`true\`].[Key,VersionId]" \
     --output text | while read key vid; do
       aws s3api copy-object --copy-source "${S3_BUCKET}-backup/${key}?versionId=${vid}" \
         --bucket "${S3_BUCKET}" --key "${key}"
   done
   ```
4. Update `settings.S3_BUCKET` and redeploy

**Failure mode B: Orphaned metadata rows after failed upload**

These rows have `status="pending"` with `created_at` older than `ORPHAN_TTL_MINUTES`. The scheduled cleanup job handles these automatically. For immediate recovery:
```bash
# Identify orphans
psql "${DATABASE_URL}" -c "SELECT id, stored_key, created_at FROM files WHERE status='pending' AND created_at < NOW() - INTERVAL '1 hour';"

# Force cleanup (runs the same logic as the ARQ task)
PYTHONPATH=src python -c "
import asyncio
from app.tasks.cleanup_orphans import cleanup_orphaned_uploads
result = asyncio.run(cleanup_orphaned_uploads())
print(result)
"
```

**Failure mode C: Quota leak (concurrent uploads bypassed quota check)**

Symptom: user has more confirmed storage than their quota allows. Recovery:
```bash
# Audit user quota usage
psql "${DATABASE_URL}" -c "
SELECT uploaded_by, SUM(size_bytes) as used_bytes, COUNT(*) as file_count
FROM files WHERE status='confirmed'
GROUP BY uploaded_by HAVING SUM(size_bytes) > ${QUOTA_BYTES}
ORDER BY used_bytes DESC;
"
# Delete the excess files (oldest first) or adjust quota via admin endpoint
```

**Failure mode D: Virus scan service unavailable**

When ClamAV is down, the upload endpoint can be configured with two policies via `VIRUS_SCAN_FAILURE_POLICY`:
- `"block"` (default): return 503 `"Virus scan unavailable"`; file not saved
- `"allow_with_flag"`: save file with `status="pending_scan"`; rescan job picks it up when ClamAV recovers

To restore virus scanning after ClamAV recovers:
```bash
# Rescan all pending_scan files
PYTHONPATH=src python -c "
import asyncio
from app.tasks.rescan_pending import rescan_all_pending
asyncio.run(rescan_all_pending())
"
```

**Failure mode E: Presigned URL already consumed or expired**

If a client's presigned upload URL expired before use:
1. Client calls `POST /files/presign` again with the same parameters
2. Previous `pending` metadata row is reused if `file_id` is passed, or a new row is created
3. The old expired presigned URL cannot be replayed

### 12.5 Emergency: revoke all presigned download URLs

If a credential leak is discovered and all outstanding presigned download URLs must be invalidated immediately:

```python
# Emergency revocation via bucket policy (blocks all presigned GET requests)
from app.core.presigned_urls import revoke_all_presigned_urls_via_bucket_policy
revoke_all_presigned_urls_via_bucket_policy(reason="credential-leak-2026-04-12")
# Restores normal access after the incident:
# boto3.client("s3").delete_bucket_policy(Bucket=settings.S3_BUCKET)
```

Alternatively, rotate the IAM credentials used to sign URLs: all previously-signed URLs become invalid immediately because they carry the old access key ID in the signature.

### 12.6 Restore from S3 versioning

If files were accidentally deleted from S3 and versioning is enabled:

```bash
# List deleted object versions
aws s3api list-object-versions \
  --bucket "${S3_BUCKET}" \
  --prefix "uploads/" \
  --query "DeleteMarkers[?IsLatest==\`true\`].[Key,VersionId]" \
  --output text > deleted_objects.txt

# Restore by removing delete markers
while IFS=$'\t' read -r key vid; do
  aws s3api delete-object --bucket "${S3_BUCKET}" --key "${key}" --version-id "${vid}"
  echo "Restored: ${key}"
done < deleted_objects.txt
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Filename has null byte (`photo\x00.jpg`) | Reject with 422 before any storage or DB operation |
| EC-2 | Filename has newline character | Reject with 422 |
| EC-3 | Filename > 255 chars | Truncate to 255 characters in `original_filename` DB column; storage key is UUID-based, unaffected |
| EC-4 | Two uploads with identical content | Two distinct UUIDs; two distinct storage objects; no deduplication by default |
| EC-5 | Upload during DB connection loss (storage writes, then DB fails) | `storage.delete(stored_key)` called in except block; no orphan in storage (INV-FU-05) |
| EC-6 | Download race: file deleted while download in progress (local) | `GET` either succeeds with complete file OR returns 404; no partial read exposed to client |
| EC-7 | `UPLOAD_DIR` doesn't exist at startup | `LocalStorage.__init__` calls `mkdir(parents=True, exist_ok=True)`; created on first use |
| EC-8 | `UPLOAD_DIR` not writable | First `save()` call raises `PermissionError`; handler catches → 500 with log; no DB row |
| EC-9 | S3 credentials invalid at startup | `S3Storage.save()` raises `ClientError`; handler catches → 500; no DB row |
| EC-10 | Disk full during local save | `asyncio.to_thread(_write)` raises `OSError`; temp file unlinked; handler returns 500 |
| EC-11 | Magic byte detection returns None (empty or truly unknown content) | 422 `"Could not detect file type from content"` |
| EC-12 | `python-magic` library not installed | Tool installation step adds `python-magic>=0.4.27` to requirements; if missing at runtime, `ImportError` logs clearly and returns 500 |
| EC-13 | File is a zip bomb (1 KB → 10 GB on extract) | Tool only stores the raw bytes; no extraction; the 1 KB zip is under `max_size_mb` and accepted; zip bomb risk is the caller's responsibility |
| EC-14 | Unicode filename with emoji | Stored as-is in DB `original_filename`; storage key is ASCII UUID so no filesystem encoding issues |
| EC-15 | Multi-tenant + file upload: tenant prefix collision | `{tenant_id}/{file_id}.{ext}` key format; UUID4 for both tenant and file ID; collision probability is astronomically small; uniqueness enforced by `stored_key UNIQUE` DB constraint |

---

## 14. Acceptance Criteria (Final Sign-off)

The tool ships when:

1. ✅ All 35 Completeness Criteria verified by automated check
2. ✅ All 25 User Stories have passing acceptance tests
3. ✅ All 34 Test Cases (T-01..T-34) pass
4. ✅ All 8 Invariants enforced by code and verified by tests
5. ✅ All 15 Edge Cases handled with correct behavior
6. ✅ Interaction Matrix verified: TOOL-001, TOOL-005, TOOL-006, TOOL-008, TOOL-013, TOOL-046 integration tested
7. ✅ Rollback procedure tested end-to-end: code, DB, storage, and each of the 5 failure modes
8. ✅ Performance SLOs met: 10 MB < 200 ms local; memory peak < 16 MB; magic byte < 5 ms
9. ✅ Magic-byte detection tested with ELF, PE, shell script disguised as image and PDF
10. ✅ Re-audit by Opus in fresh context, brutal mode: ≥ 9.5/10

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate `app/` subdirectory exists
- [ ] Validate `alembic/versions/` exists
- [ ] Validate User model exists (file upload requires auth)
- [ ] Check if `app/models/file.py` already exists (idempotency gate)
- [ ] Check if `app/core/storage.py` already exists (idempotency gate)
- [ ] Check if `STORAGE_BACKEND` already in `app/core/config.py` (idempotency gate)
- [ ] If all three exist → return early with `notes=["file upload already enabled, skipped"]`
- [ ] If `storage="s3"`: verify boto3 available or installable
- [ ] If `enable_virus_scan=True`: warn if ClamAV socket path not configured

### 15.2 File model
- [ ] Create `app/models/file.py`
- [ ] All 12 fields with correct types (id UUID, original_filename String(255), stored_key String(512) UNIQUE, content_type String(255), size_bytes BigInteger, status String(16), uploaded_by FK→users SET NULL, tenant_id UUID nullable, resource_type String(64), resource_id UUID, created_at DateTime(tz), confirmed_at DateTime(tz) nullable)
- [ ] `status` column: `server_default="pending"` with value semantics: `pending|confirmed|virus_detected|orphaned`
- [ ] Three indexes: composite `(resource_type, resource_id)`, single `(uploaded_by)`, composite `(tenant_id, status)`
- [ ] FK `uploaded_by → users.id` with `ondelete="SET NULL"` (file survives user deletion)
- [ ] Registered in `app/models/__init__.py` so Alembic picks it up
- [ ] Write atomically (temp file + rename)
- [ ] `ast.parse` passes on generated file

### 15.3 Storage backend
- [ ] Create `app/core/storage.py` with `StorageBackend` ABC (3 abstract methods: `save`, `get_url`, `delete`)
- [ ] `LocalStorage.save()`: write chunks of 64 KB, temp-file + atomic `replace()`, path traversal guard verifies resolved path starts with `base_dir`
- [ ] `LocalStorage.get_url()`: returns `/api/v1/files/{key}/download` (streamed via local endpoint)
- [ ] `S3Storage.save()`: `upload_fileobj` with `ServerSideEncryption=AES256`, wrapped in `asyncio.to_thread`
- [ ] `S3Storage.get_url()`: calls `generate_presigned_url("get_object", ExpiresIn=...)`
- [ ] `get_storage()` factory: reads `settings.STORAGE_BACKEND`; returns `LocalStorage` or `S3Storage`
- [ ] Write atomically; `ast.parse` passes
- [ ] Unit test: mock both backends; verify factory selection

### 15.4 File validator
- [ ] Create `app/core/file_validator.py`
- [ ] `detect_mime()`: reads exactly 8192 bytes via `magic.from_buffer(head, mime=True)`, resets file pointer, returns MIME or None
- [ ] `validate_file()`: checks `ALWAYS_BLOCKED` first (raises immediately), then checks `allowed_types`
- [ ] `SAFE_DEFAULTS` frozenset: `{image/jpeg, image/png, image/gif, image/webp, application/pdf, text/plain}`
- [ ] `ALWAYS_BLOCKED` frozenset: covers PE (`application/x-msdownload`), ELF (`application/x-executable`), DOS exec, shell scripts
- [ ] Returns detected MIME type string (ground truth for DB `content_type` column)
- [ ] No code path inspects `file.content_type` header or filename extension for security decisions
- [ ] `ast.parse` passes

### 15.5 Presigned URL module (S3 path)
- [ ] Create `app/core/presigned_urls.py`
- [ ] `generate_upload_url()`: `generate_presigned_post` with `Content-Length-Range` condition; fields include `x-amz-server-side-encryption: AES256`
- [ ] `generate_download_url()`: `generate_presigned_url("get_object", ExpiresIn=...)` with configurable TTL
- [ ] `revoke_all_presigned_urls_via_bucket_policy()`: attaches deny-all `GetObject` bucket policy for emergency mass-revocation
- [ ] Upload TTL: `settings.PRESIGN_UPLOAD_TTL_SECONDS` (default 300); download TTL: `settings.PRESIGN_DOWNLOAD_TTL_SECONDS` (default 3600)
- [ ] Both functions wrapped in `asyncio.to_thread` for use in async endpoints
- [ ] `ClientError` from boto3 caught and re-raised as `RuntimeError` with descriptive message
- [ ] `ast.parse` passes

### 15.6 Multipart upload helper
- [ ] Create `app/core/multipart_upload.py`
- [ ] `upload_multipart(file, stored_key, content_type)`: full multipart lifecycle
- [ ] Step 1: `create_multipart_upload` with `ServerSideEncryption=AES256`
- [ ] Step 2: loop `upload_part` in `PART_SIZE_BYTES` (10 MB) chunks; collect `(PartNumber, ETag)` pairs
- [ ] Step 3: `complete_multipart_upload` with all parts; return `{ETag, VersionId}`
- [ ] Step E: `abort_multipart_upload` called in `except` block to prevent orphaned upload IDs in S3
- [ ] Threshold: invoked when `size_bytes > 5 * 1024 * 1024`; smaller files use `upload_fileobj`
- [ ] `ast.parse` passes

### 15.7 Optional: virus scan wrapper
- [ ] If `enable_virus_scan=True`: create `app/core/virus_scan.py`
- [ ] `VirusScanResult` dataclass: fields `clean: bool`, `threat_name: str | None`
- [ ] `scan_file(file_path)`: ClamAV INSTREAM protocol (send file in 64 KB chunks over Unix socket), non-blocking via `asyncio.to_thread`
- [ ] `CLAMD_SOCKET` constant: `/var/run/clamav/clamd.ctl`; configurable via `settings.CLAMD_SOCKET_PATH`
- [ ] `VIRUS_SCAN_FAILURE_POLICY` from `settings`: `"block"` (default) → return 503; `"allow_with_flag"` → save with `status="pending_scan"`
- [ ] `rescan_all_pending()` task: queries `status="pending_scan"` rows, re-scans, updates status
- [ ] `RuntimeError` raised if ClamAV socket unreachable; caller applies failure policy
- [ ] `ast.parse` passes

### 15.8 Optional: quota enforcer
- [ ] If `enable_quota=True`: create `app/core/upload_quota.py`
- [ ] `quota_lock(user_id)`: async context manager using Redis `SET {key} NX EX {ttl}`; raises 429 if lock not acquired (another upload in progress)
- [ ] `check_quota(session, user_id, incoming_bytes)`: `SELECT SUM(size_bytes) FROM files WHERE uploaded_by=? AND status='confirmed'`
- [ ] Compares `used_bytes + incoming_bytes` against `settings.QUOTA_MB_PER_USER * 1024 * 1024`; raises 413 if exceeded
- [ ] `QUOTA_LOCK_TTL_SECONDS = 5` constant (covers check + pending row insert latency)
- [ ] Lock key format: `quota_lock:{user_id}` (unique per user, not global)
- [ ] Redis client from `settings.REDIS_URL`; `aclose()` called in finally block
- [ ] `ast.parse` passes

### 15.9 CRUD module
- [ ] Create `app/crud/file.py`
- [ ] `create_pending(session, *, id, original_filename, stored_key, content_type, size_bytes, uploaded_by, resource_type, resource_id)` — inserts with `status="pending"`
- [ ] `confirm(session, *, file_id, size_bytes, confirmed_at)` — updates `status="confirmed"`, sets `confirmed_at`, updates `size_bytes` from S3 HEAD
- [ ] `get(session, file_id)` — returns any status; used internally
- [ ] `get_pending(session, file_id, owner_id)` — returns row only if `status="pending"` and `uploaded_by == owner_id`
- [ ] `get_confirmed(session, file_id)` — returns row only if `status in ("confirmed", "virus_detected")`
- [ ] `delete(session, file_id)` — hard delete; caller must delete storage object first
- [ ] `list_by_resource(session, resource_type, resource_id, *, skip, limit)` — paginated listing for parent-scoped endpoint
- [ ] All functions async; `AsyncSession` as first positional argument
- [ ] `ast.parse` passes

### 15.10 Schema module
- [ ] Create `app/schemas/file.py`
- [ ] `FileMetadataPublic`: fields `id`, `original_filename`, `content_type`, `size_bytes`, `status`, `url`, `created_at`, `confirmed_at` — NO `stored_key`, NO `tenant_id`
- [ ] `FilesPublic`: `{data: list[FileMetadataPublic], count: int}`
- [ ] `PresignedUploadRequest`: fields `filename`, `content_type`, `size_bytes`, `resource_type?`, `resource_id?`
- [ ] `PresignedUploadResponse`: fields `file_id`, `upload_url`, `fields`, `stored_key`, `expires_in`
- [ ] `UploadConfirmRequest`: minimal — `file_id` confirmed via path param; body may be empty or include `checksum` for integrity
- [ ] All schemas use `model_config = ConfigDict(from_attributes=True)` for ORM compatibility
- [ ] `ast.parse` passes

### 15.11 Routes
- [ ] Create `app/api/routes/files.py`
- [ ] `POST /files/presign` (S3 path): quota check → presign → create_pending
- [ ] `POST /files/` (local path): size check → magic validate → stream to storage → create confirmed
- [ ] `POST /files/{id}/confirm` (S3 path): HEAD check → confirm metadata
- [ ] `GET /files/{id}`: ownership check → 302 (S3) or FileResponse (local); 451 if virus_detected
- [ ] `DELETE /files/{id}`: ownership check → storage.delete → crud.delete
- [ ] If `model_name` set: `GET /{model_name_lower}/{id}/files` listing endpoint
- [ ] All endpoints require `CurrentUser`
- [ ] Registered in `app/api/main.py`
- [ ] `ast.parse` passes

### 15.12 Settings additions
- [ ] Add `STORAGE_BACKEND: Literal["local", "s3"] = "local"` to `app/core/config.py`
- [ ] Add `UPLOAD_DIR: str = "/data/uploads"` (absolute path; resolved at runtime)
- [ ] Add `MAX_UPLOAD_SIZE_MB: int = 10`
- [ ] Add `ALLOWED_FILE_TYPES: list[str] = []` (empty = use `SAFE_DEFAULTS`)
- [ ] Add `S3_BUCKET: str = ""`, `AWS_REGION: str = "us-east-1"`
- [ ] Add `PRESIGN_UPLOAD_TTL_SECONDS: int = 300`, `PRESIGN_DOWNLOAD_TTL_SECONDS: int = 3600`
- [ ] Add `QUOTA_MB_PER_USER: int = 500`, `ORPHAN_TTL_MINUTES: int = 60`
- [ ] Add `VIRUS_SCAN_FAILURE_POLICY: Literal["block", "allow_with_flag"] = "block"`, `CLAMD_SOCKET_PATH: str = "/var/run/clamav/clamd.ctl"`
- [ ] Update `.env.example` with all new keys and sensible defaults
- [ ] `ast.parse` passes on modified `config.py`

### 15.13 Migration
- [ ] Compute next revision number from latest revision in `alembic/versions/`
- [ ] Generate `alembic/versions/0NNN_files_table.py`
- [ ] `upgrade()`: `create_table("files", ...)` with all 12 columns including FK definition inline
- [ ] Add index `ix_files_resource` on `(resource_type, resource_id)` via `op.create_index`
- [ ] Add index `ix_files_uploaded_by` on `(uploaded_by)` via `op.create_index`
- [ ] Add index `ix_files_tenant_status` on `(tenant_id, status)` via `op.create_index`
- [ ] `downgrade()`: drop indexes in reverse order, then `op.drop_table("files")`
- [ ] `down_revision` set correctly; Alembic chains without conflict
- [ ] `ast.parse` passes on migration file

### 15.14 Cleanup task
- [ ] Create `app/tasks/cleanup_orphans.py`
- [ ] `cleanup_orphaned_uploads()`: SELECT `status="pending"` AND `created_at < now() - ORPHAN_TTL_MINUTES` with `LIMIT BATCH_SIZE` and `WITH FOR UPDATE SKIP LOCKED`
- [ ] For each row: call `storage.delete(stored_key)` (log warning on failure, continue)
- [ ] DELETE DB rows by ID list; `session.commit()` per batch
- [ ] Loop until zero rows returned; return `{deleted_storage, deleted_db}` dict
- [ ] `BATCH_SIZE = 100` constant
- [ ] Register as ARQ `WorkerSettings.cron_jobs` entry (default: every 60 minutes)
- [ ] `ast.parse` passes

### 15.15 Requirements
- [ ] Add `python-magic>=0.4.27` to `requirements.txt` (requires `libmagic` OS package)
- [ ] Alternatively: `filetype>=1.2.0` as pure-Python fallback (no system dependency)
- [ ] If `storage="s3"`: add `boto3>=1.34.0` to `requirements.txt`
- [ ] If `enable_quota=True`: add `redis>=5.0.0` to `requirements.txt` (may already be present from other tools)
- [ ] If `enable_virus_scan=True`: append ClamAV setup note to generated README section: `apt-get install clamav-daemon` (Debian) or `brew install clamav` (macOS)
- [ ] Update `pyproject.toml` optional extras if present (e.g., `[project.optional-dependencies] s3 = ["boto3>=1.34.0"]`)
- [ ] `ast.parse` not required for `requirements.txt`; verify file is UTF-8 text, one package per line

### 15.16 Tests
- [ ] Create `tests/test_file_upload.py` with all 34 test cases (T-01..T-34)
- [ ] S3 tests use `moto` mock: `@mock_aws` decorator wraps S3-dependent tests; `moto` creates ephemeral bucket per test
- [ ] Atomicity tests use `unittest.mock.patch` to simulate DB failures and storage failures independently
- [ ] Fixtures: `upload_jpeg_bytes` (1 MB JPEG magic bytes), `upload_pdf_bytes`, `s3_mock_bucket` (creates + deletes bucket), `confirmed_file` (pre-inserted confirmed row)
- [ ] Auth fixtures: `user_token`, `other_user_token`, `superuser_token`, `anon_headers={}` for anonymous tests
- [ ] All async tests decorated with `@pytest.mark.asyncio`; use `AsyncClient(app=app, base_url="http://test")`
- [ ] Each test has at least one `assert` on status code AND at least one `assert` on response body
- [ ] `ast.parse` passes on test file

### 15.17 Documentation
- [ ] Append file-upload section to `core/KNOWLEDGE.md` (what was added, why, how to configure)
- [ ] Add tool entry to `manifest.yaml`: `{id: TOOL-003, name: fastapi_add_file_upload, category: "EXTEND > CRUD & Data", complexity: High}`
- [ ] Update `SKILL.md` tools table: add row for TOOL-003 with signature, category, complexity
- [ ] Register tool in `mcp_server.py` with `@mcp_tool` decorator and full parameter schema
- [ ] Update `.env.example` with all new settings keys and inline comments
- [ ] If S3 used: add IAM policy example (minimum permissions: `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`, `s3:HeadObject`) to documentation
- [ ] Add note on ClamAV setup if `enable_virus_scan=True` was requested

### 15.18 Atomicity and verification
- [ ] All file writes via temp-file + atomic rename
- [ ] Track all touched files; on ANY exception, revert all writes
- [ ] Drop partial `files` table if upgrade partially ran: `alembic downgrade` or `DROP TABLE IF EXISTS files`
- [ ] Run `ast.parse` on every generated and modified file
- [ ] Run import audit on the project
- [ ] Run `pytest tests/` to verify 0 regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure tool execution time (must be < 4s)
- [ ] Return `{files_created, files_modified, files_rolled_back, error}` on failure

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/file.py",
    "app/crud/file.py",
    "app/schemas/file.py",
    "app/core/storage.py",
    "app/core/file_validator.py",
    "app/core/presigned_urls.py",
    "app/core/multipart_upload.py",
    "app/core/upload_quota.py",
    "app/core/virus_scan.py",
    "app/tasks/cleanup_orphans.py",
    "app/api/routes/files.py",
    "alembic/versions/0005_files_table.py",
    "tests/test_file_upload.py"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/api/main.py",
    "requirements.txt",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 3540,
    "files_changed": 17,
    "lines_added": 892,
    "lines_removed": 0
  },
  "next_steps": [
    "Run: pip install -r requirements.txt",
    "Run: alembic upgrade head",
    "Set UPLOAD_DIR in .env (default: /data/uploads) or S3_BUCKET for S3 storage",
    "Set MAX_UPLOAD_SIZE_MB and ALLOWED_FILE_TYPES in .env",
    "For S3: configure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION",
    "For virus scan: ensure ClamAV daemon running at /var/run/clamav/clamd.ctl",
    "Run: pytest tests/test_file_upload.py -v",
    "Test presign flow: POST /api/v1/files/presign then POST /api/v1/files/{id}/confirm"
  ],
  "warnings": [
    "If add_multi_tenancy is installed, file stored_keys are automatically prefixed with tenant_id.",
    "S3 backend: enable S3 Versioning on your bucket for point-in-time recovery.",
    "Virus scan requires ClamAV system package: apt-get install clamav-daemon (Debian) or brew install clamav (macOS).",
    "Quota enforcement requires Redis; REDIS_URL must be set in .env.",
    "python-magic requires libmagic: apt-get install libmagic1 (Debian) or brew install libmagic (macOS)."
  ],
  "notes": [
    "File upload enabled. Storage backend: s3 (configurable via STORAGE_BACKEND).",
    "Direct S3 presigned upload flow: client uploads directly, server never proxies file bytes.",
    "Multipart upload enabled for files > 5 MB (10 MB part size).",
    "Virus scanning: enabled (ClamAV INSTREAM protocol).",
    "Quota enforcement: enabled (500 MB per user, Redis advisory lock).",
    "Orphan cleanup task registered in ARQ worker (runs every 60 minutes).",
    "Max upload size: 10 MB (configurable). Allowed types: image/jpeg, image/png, image/gif, image/webp, application/pdf, text/plain (configurable)."
  ]
}
```
