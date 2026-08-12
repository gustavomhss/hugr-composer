---
spec_id: "TOOL-060"
tool_name: "add_s3_storage"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-S3-01"
  - "INV-S3-02"
  - "INV-S3-03"
  - "INV-S3-04"
  - "INV-S3-05"
  - "INV-S3-06"
  - "INV-S3-07"
  - "INV-S3-08"
  - "INV-S3-09"
  - "INV-S3-10"
  - "INV-S3-11"
  - "INV-S3-12"
  - "INV-S3-13"
  - "INV-S3-14"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
  - "CC-21"
  - "CC-22"
  - "CC-23"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-2"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
  - "T-23"
tags:
  - "performance"
  - "data"
  - "resiliency"
  - "realtime"
  - "compliance"
---
# TOOL-060: add_s3_storage

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_s3_storage` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, boto3>=1.35.0, pydantic-settings, Starlette |
| Signature | `add_s3_storage(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_s3_storage", "description": "Add production-grade S3/MinIO object storage with presigned URL upload/download, content-type validation, upload-size middleware, and REST routes.", "tags": ["extend", "infrastructure"], "entry": "add_s3_storage"}` |
| Files created (typical) | 5 — `app/storage/__init__.py`, `app/storage/client.py`, `app/storage/config.py`, `app/storage/middleware.py`, `app/api/routes/storage.py` |
| Files modified (typical) | 2–3 — `app/core/config.py`, `app/routes/__init__.py` (if present), `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_s3_storage` tool installs production-grade S3/MinIO object storage into a FastAPI project — covering the boto3 client wrapper, configuration dataclass, upload-size enforcement middleware, and presigned-URL REST routes — without any file-proxying through the API server. Teams that reach for `UploadFile` and `shutil.copyfileobj` in FastAPI handlers are making a scalability and cost mistake they will discover in production: a 1 GB image upload holds a Gunicorn worker for the entire transfer duration, saturates the API server's network interface, and generates an egress bill for bytes that should have gone directly from the browser to object storage. The correct architecture uses presigned URLs — the API server generates a time-limited, scope-limited credential for a single object key; the client uploads directly to S3 or MinIO; the API server never buffers binary data.

This tool generates the entire production kit: (a) `app/storage/client.py` — an `S3Client` class that imports `boto3` **lazily** inside `__init__` so the application boots cleanly on machines where boto3 is absent (tests, bare metal dev), exposes `generate_key(filename, prefix)` that produces `{prefix}/{uuid4}/{filename}` keys eliminating both collision and path-traversal risks, `presigned_upload_url(key, content_type, expiration)` and `presigned_download_url(key, expiration)` backed by `boto3.client.generate_presigned_url`, and `delete_object(key)` for object lifecycle management; a module-level singleton `get_s3_client()` that is created lazily on first call; (b) `app/storage/config.py` — a frozen `StorageConfig` dataclass built via `StorageConfig.from_settings()` that provides a typed, independently-testable view over the eight S3-related settings fields; (c) `app/storage/middleware.py` — `UploadSizeMiddleware` extending `BaseHTTPMiddleware` that reads `Content-Length` on PUT and POST requests and returns HTTP 413 before the request body is consumed by any handler; (d) `app/api/routes/storage.py` — three REST endpoints: `POST /storage/upload` (validates content type against `S3_ALLOWED_CONTENT_TYPES`, generates a collision-safe key, returns `UploadResponse` with the presigned PUT URL); `GET /storage/{key:path}` (returns `DownloadResponse` with the presigned GET URL); `DELETE /storage/{key:path}` (deletes the object, returns 204); (e) `app/storage/__init__.py` re-exporting the public surface.

Key design decisions: MinIO is supported as a drop-in alternative to AWS S3 via `settings.S3_ENDPOINT_URL` — omitting this field routes to AWS; the API server never buffers binary data (presigned URLs expire in `settings.S3_PRESIGNED_URL_EXPIRATION` seconds, default 3600); object keys are generated as `{prefix}/{uuid4}/{original_filename}` to prevent both collision (UUID segment) and path-traversal (the `replace("..", "").lstrip("/")` sanitisation); content-type validation raises HTTP 415 before issuing any presigned URL — the whitelist lives in `settings.S3_ALLOWED_CONTENT_TYPES`; upload-size enforcement is applied by middleware reading `Content-Length` so oversized requests are rejected without consuming worker memory; the tool is idempotent — a second run detects `S3Client` in `app/storage/client.py` and returns `status="no_op"` with zero file writes.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (T-18) |
| Python files created | ≥ 5 | `__init__`, client, config, middleware, routes — all five must be emitted (T-04) |
| Files modified | ≥ 2 | `app/core/config.py` (S3 settings) and `requirements.txt` (boto3) — at least two of these three must exist (T-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (T-07) |
| `POST /storage/upload` latency | < 100 ms | `generate_presigned_url` is a local HMAC operation — no network call to S3 |
| `GET /storage/{key}` latency | < 100 ms | Same HMAC operation; no object data transferred through API |
| `DELETE /storage/{key}` latency | < 500 ms | Single S3 `DeleteObject` API call; bounded by AWS/MinIO RTT |
| `Content-Length` enforcement | Before request body consumed | `UploadSizeMiddleware.dispatch` checks the header; 413 is returned without reading the body |
| Key collision probability | Negligible | UUIDv4 segment provides 2^122 entropy per key |
| Presigned URL expiration default | 3600 s | Configurable via `settings.S3_PRESIGNED_URL_EXPIRATION`; client must PUT within this window |
| Max upload size default | 50 MB (52,428,800 bytes) | Configurable via `settings.S3_MAX_UPLOAD_SIZE_BYTES`; enforced by middleware before S3 interaction |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no S3 integration
│   ├── core/
│   │   └── config.py        # Settings class, no S3_* fields
│   └── api/
│       └── routes/          # No storage.py
├── requirements.txt         # no boto3
└── (no app/storage/)
```

File uploads are handled inline via FastAPI's `UploadFile` — every upload saturates a worker thread for the full transfer duration, egress is double-billed (client → API → S3), and there is no upload-size enforcement beyond FastAPI's default body limit.

### 4.2 S3 client wrapper (lazy boto3): AFTER

```python
# app/storage/client.py
"""Lazy boto3 S3 client wrapper.

``boto3`` is imported INSIDE the class constructor so the application
can boot without the ``boto3`` package installed.  ``get_s3_client``
returns a module-level singleton; callers that need a fresh instance
(e.g. tests) should instantiate ``S3Client`` directly.

Key-generation contract:
    Every key is ``{prefix}/{uuid4}/{original_filename}``.  The UUID
    segment prevents collisions between users uploading the same filename
    and eliminates path-traversal risk from filenames containing ``..``.
"""
from __future__ import annotations

import mimetypes
import uuid
from typing import Any

from app.core.config import settings


class S3Client:
    """Thin wrapper around ``boto3.client('s3')`` with lazy import."""

    def __init__(self) -> None:
        """Initialise the S3Client, importing boto3 lazily."""
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
        """Return a collision-safe object key for *filename*.

        Args:
            filename: Original filename from the client request.
            prefix: Optional path prefix (overrides settings default when
                provided and non-empty).

        Returns:
            Key string formatted as ``{prefix}/{uuid}/{filename}``.
        """
        key_prefix = prefix or settings.S3_KEY_PREFIX
        safe_name = filename.replace("..", "").lstrip("/")
        return f"{key_prefix}/{uuid.uuid4()}/{safe_name}"

    def presigned_upload_url(
        self,
        key: str,
        content_type: str,
        expiration: int | None = None,
    ) -> str:
        """Return a presigned PUT URL for a direct client-to-S3 upload."""
        exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key, "ContentType": content_type},
            ExpiresIn=exp,
            HttpMethod="PUT",
        )

    def presigned_download_url(self, key: str, expiration: int | None = None) -> str:
        """Return a presigned GET URL for a direct client-to-S3 download."""
        exp = expiration if expiration is not None else settings.S3_PRESIGNED_URL_EXPIRATION
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": key},
            ExpiresIn=exp,
        )

    def delete_object(self, key: str) -> None:
        """Delete an object from the configured bucket."""
        self._client.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=key)

    def guess_content_type(self, filename: str) -> str:
        """Guess the MIME type of *filename* using the stdlib."""
        mime, _ = mimetypes.guess_type(filename)
        return mime or "application/octet-stream"


_s3_client_singleton: S3Client | None = None


def get_s3_client() -> S3Client:
    """Return the module-level ``S3Client`` singleton."""
    global _s3_client_singleton
    if _s3_client_singleton is None:
        _s3_client_singleton = S3Client()
    return _s3_client_singleton
```

### 4.3 StorageConfig dataclass: AFTER

```python
# app/storage/config.py
"""StorageConfig dataclass — typed view over S3-related settings fields."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import settings


@dataclass(frozen=True)
class StorageConfig:
    """Typed snapshot of S3/MinIO settings for a single request context.

    Attributes:
        bucket_name: S3 bucket name.
        region: AWS region (or MinIO region label).
        endpoint_url: Optional custom endpoint for MinIO / compatible stores.
        presigned_url_expiration: Seconds before a presigned URL expires.
        max_upload_size_bytes: Maximum allowed upload size in bytes.
        allowed_content_types: Whitelist of accepted MIME types.
        key_prefix: Default path prefix for generated object keys.
    """

    bucket_name: str
    region: str
    endpoint_url: str
    presigned_url_expiration: int
    max_upload_size_bytes: int
    allowed_content_types: list[str]
    key_prefix: str

    @classmethod
    def from_settings(cls) -> "StorageConfig":
        """Build a ``StorageConfig`` from the global settings object."""
        return cls(
            bucket_name=settings.S3_BUCKET_NAME,
            region=settings.S3_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL,
            presigned_url_expiration=settings.S3_PRESIGNED_URL_EXPIRATION,
            max_upload_size_bytes=settings.S3_MAX_UPLOAD_SIZE_BYTES,
            allowed_content_types=list(settings.S3_ALLOWED_CONTENT_TYPES),
            key_prefix=settings.S3_KEY_PREFIX,
        )
```

### 4.4 Upload-size enforcement middleware: AFTER

```python
# app/storage/middleware.py
"""Upload-size enforcement middleware.

``UploadSizeMiddleware`` reads ``Content-Length`` from incoming PUT / POST
requests and rejects them before the request body is consumed.
"""
from __future__ import annotations

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings


class UploadSizeMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds the configured limit."""

    def __init__(self, app: ASGIApp, max_size: int | None = None) -> None:
        """Initialise the middleware.

        Args:
            app: The ASGI application to wrap.
            max_size: Override maximum bytes. Defaults to
                ``settings.S3_MAX_UPLOAD_SIZE_BYTES``.
        """
        super().__init__(app)
        self.max_size = max_size if max_size is not None else settings.S3_MAX_UPLOAD_SIZE_BYTES

    async def dispatch(self, request: Request, call_next: object) -> Response:
        """Intercept the request and reject oversized uploads."""
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
```

### 4.5 Presigned URL REST routes: AFTER

```python
# app/api/routes/storage.py
"""REST routes for S3/MinIO presigned URL operations.

Routes
------
POST   /storage/upload          Return a presigned PUT URL for direct upload.
GET    /storage/{key:path}      Return a presigned GET URL for direct download.
DELETE /storage/{key:path}      Delete an object from the bucket.

The API server never buffers binary data — all file I/O goes directly
between the client and S3/MinIO via the presigned URLs.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.storage.client import get_s3_client

router = APIRouter(prefix="/storage", tags=["storage"])


class UploadRequest(BaseModel):
    """Request body for presigned upload URL generation."""

    filename: str = Field(..., min_length=1, max_length=255)
    content_type: str = Field(..., min_length=1)
    prefix: str = Field(default="", max_length=200)


class UploadResponse(BaseModel):
    """Response body for a presigned upload URL."""

    upload_url: str
    key: str
    expires_in: int


class DownloadResponse(BaseModel):
    """Response body for a presigned download URL."""

    download_url: str
    key: str
    expires_in: int


def _validate_content_type(content_type: str) -> None:
    """Raise HTTP 415 if *content_type* is not in the allowed list."""
    allowed = settings.S3_ALLOWED_CONTENT_TYPES
    if allowed and content_type not in allowed:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Content-Type '{content_type}' is not allowed. "
                f"Allowed types: {', '.join(allowed)}"
            ),
        )


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_200_OK)
def create_upload_url(body: UploadRequest) -> UploadResponse:
    """Return a presigned PUT URL for a direct client-to-S3 upload."""
    _validate_content_type(body.content_type)
    client = get_s3_client()
    key = client.generate_key(body.filename, prefix=body.prefix)
    url = client.presigned_upload_url(key, body.content_type)
    return UploadResponse(
        upload_url=url,
        key=key,
        expires_in=settings.S3_PRESIGNED_URL_EXPIRATION,
    )


@router.get("/{key:path}", response_model=DownloadResponse)
def create_download_url(key: str) -> DownloadResponse:
    """Return a presigned GET URL for a direct client-to-S3 download."""
    client = get_s3_client()
    url = client.presigned_download_url(key)
    return DownloadResponse(
        download_url=url,
        key=key,
        expires_in=settings.S3_PRESIGNED_URL_EXPIRATION,
    )


@router.delete("/{key:path}", status_code=status.HTTP_204_NO_CONTENT)
def delete_object(key: str) -> None:
    """Delete an object from the configured S3 bucket."""
    client = get_s3_client()
    client.delete_object(key)
```

### 4.6 Config patch (S3 settings injected inside `class Settings`): AFTER

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- S3/MinIO object storage — added by add_s3_storage tool ---
    S3_BUCKET_NAME: str = "my-app-bucket"
    S3_REGION: str = "us-east-1"
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY_ID: str = ""
    S3_SECRET_ACCESS_KEY: str = ""
    S3_PRESIGNED_URL_EXPIRATION: int = 3600
    S3_MAX_UPLOAD_SIZE_BYTES: int = 52428800
    S3_ALLOWED_CONTENT_TYPES: list[str] = [
        "image/jpeg", "image/png", "image/gif", "image/webp",
        "application/pdf", "text/plain",
    ]
    S3_KEY_PREFIX: str = "uploads"
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land **inside** the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables. `S3_ENDPOINT_URL` being empty by default routes requests to AWS; setting it to `http://localhost:9000` routes to a local MinIO instance.

### 4.7 Typical caller usage (after install)

```python
# Request a presigned upload URL:
# POST /api/v1/storage/upload
# Body: {"filename": "profile.png", "content_type": "image/png"}
# Response: {"upload_url": "https://s3.amazonaws.com/...", "key": "uploads/abc-uuid/profile.png", "expires_in": 3600}

# Client PUTs file directly to upload_url (no API server involvement)
# import httpx
# httpx.put(upload_url, content=file_bytes, headers={"Content-Type": "image/png"})

# Request a presigned download URL:
# GET /api/v1/storage/uploads/abc-uuid/profile.png
# Response: {"download_url": "https://s3.amazonaws.com/...", "key": "uploads/abc-uuid/profile.png", "expires_in": 3600}

# Delete an object:
# DELETE /api/v1/storage/uploads/abc-uuid/profile.png
# Response: 204 No Content
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_s3_storage` pre-flight checks `"S3Client" in app/storage/client.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | Returns success + notes before any `Path.write_text` call when `inp.dry_run` is truthy |
| QS-3 | **Every generated `.py` file AST-parses** | `_assert_parses` runs `ast.parse` on each created `.py` file; raises `SyntaxError` before returning success |
| QS-4 | **No generated function exceeds 50 LOC** | All helpers in `client.py`, `config.py`, `middleware.py`, `routes/storage.py` stay small by construction; asserted by AST walk in test harness |
| QS-5 | **boto3 is imported lazily inside `S3Client.__init__`** | `import boto3` appears inside `__init__` body, never at module level — FastAPI boots without boto3 installed |
| QS-6 | **Object keys use `{prefix}/{uuid4}/{filename}` format** | `generate_key` emits this format; UUID segment prevents collisions; `replace("..", "").lstrip("/")` sanitises the filename component |
| QS-7 | **Content-type validation raises HTTP 415 before presigning** | `_validate_content_type(body.content_type)` is called inside `create_upload_url` before any S3 API call |
| QS-8 | **Upload-size enforcement uses `Content-Length` header** | `UploadSizeMiddleware.dispatch` reads `request.headers.get("content-length")` and returns 413 without consuming the body |
| QS-9 | **MinIO support via `S3_ENDPOINT_URL`** | `S3Client.__init__` conditionally passes `endpoint_url=settings.S3_ENDPOINT_URL` when non-empty |
| QS-10 | **`S3_*` fields live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent so pydantic-settings binds env vars |
| QS-11 | **`boto3>=1.35.0` is added to `requirements.txt`** | `_patch_requirements` appends the pin only when `"boto3"` is absent; existing boto3 pin is preserved |
| QS-12 | **Storage router registered in `app/routes/__init__.py`** | `_patch_routes_init` idempotently inserts import and `include_router` call |
| QS-13 | **`app/storage/__init__.py` re-exports the public surface** | `S3Client`, `StorageConfig`, `get_s3_client` are imported and listed in `__all__` |
| QS-14 | **`StorageConfig` is a frozen dataclass** | `@dataclass(frozen=True)` prevents accidental mutation; `from_settings()` classmethod provides a clean construction path |
| QS-15 | **Prerequisites validated before write** | `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` runs first; returns `status="error"` with actionable notes on failure |
| QS-16 | **Tool records execution time** | `ToolResult.execution_time_ms` is computed via `_elapsed_ms(start)` on every return path |
| QS-17 | **`next_steps` mention boto3, bucket, and endpoint configuration** | `next_steps` list includes `pip install`, env var guidance, bucket creation, and CORS reminder |
| QS-18 | **Second run keeps project parseable** | Idempotent no-op path does not corrupt any file; all `.py` remain AST-valid after two invocations |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_s3_storage.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and `r2.files_created == []` and `r2.files_modified == []` | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree; `result.files_created == []` and `result.files_modified == []` | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 5 Python files | `len([p for p in result.files_created if p.endswith(".py")]) >= 5` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists on disk | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `S3_BUCKET_NAME`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PRESIGNED_URL_EXPIRATION` exist inside `class Settings` body with 4-space indent | String scan + indent check on line containing `S3_BUCKET_NAME` | T-08 (`test_config_fields_patched`) |
| CC-09 | `requirements.txt` contains `boto3>=` pin | `"boto3>=" in content` of `requirements.txt` | T-09 (`test_requirements_patched`) |
| CC-10 | `app/storage/client.py` exists and contains `class S3Client` | File exists + `"class S3Client" in content` | T-10 (`test_s3_client_created`) |
| CC-11 | `S3Client` exposes `presigned_upload_url` and `presigned_download_url` methods | Both method names present in `client.py` content | T-11 (`test_presigned_url_helpers`) |
| CC-12 | `app/api/routes/storage.py` exists with upload, download, and delete routes | File exists + `"/upload"` and `"delete"` (case-insensitive) and `"download"` (case-insensitive) in content | T-12 (`test_storage_routes_created`) |
| CC-13 | Storage router is registered in `app/routes/__init__.py` (when that file exists) | `"storage" in content.lower()` of `routes/__init__.py` | T-13 (`test_routes_registered`) |
| CC-14 | `boto3` is NOT a top-level import in `client.py`; `import boto3` IS inside a function body | `ast.iter_child_nodes` shows no top-level boto3 import; `"import boto3" in content` | T-14 (`test_lazy_boto3_import`) |
| CC-15 | `generate_key` uses UUID and produces `{prefix}/{uuid}/{filename}` pattern | `"generate_key" in content`; `"uuid" in content.lower()`; `"key_prefix"` or `"{prefix}"` in content | T-15 (`test_key_generation_pattern`) |
| CC-16 | Storage routes include content-type validation (HTTP 415 path) | `"content_type" in content`; `"415"` or `"UNSUPPORTED_MEDIA_TYPE"` in content; `"S3_ALLOWED_CONTENT_TYPES"` or `"allowed"` (case-insensitive) in content | T-16 (`test_content_type_validation`) |
| CC-17 | `UploadSizeMiddleware` reads `S3_MAX_UPLOAD_SIZE_BYTES` from settings and returns HTTP 413 | `middleware.py` exists + `"S3_MAX_UPLOAD_SIZE_BYTES" in content` + `"413" in content` | T-17 (`test_max_file_size_from_settings`) |
| CC-18 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-19 | `next_steps` includes boto3 / bucket configuration guidance | `result.next_steps` non-empty; lowercased join contains `"pip"` or `"boto3"`; contains `"s3_bucket_name"` or `"bucket"` | T-19 (`test_next_steps_present`) |
| CC-20 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two invocations | T-20 (`test_idempotent_project_still_parses`) |
| CC-21 | `app/storage/__init__.py` re-exports `S3Client` and `get_s3_client` | File exists + `"S3Client" in content` + `"get_s3_client" in content` | T-21 (`test_storage_package_init_re_exports`) |
| CC-22 | `app/storage/config.py` exists with `StorageConfig` and `from_settings` classmethod | File exists + `"StorageConfig" in content` + `"from_settings" in content` | T-22 (`test_storage_config_dataclass_created`) |
| CC-23 | `app/core/config.py` contains `S3_ENDPOINT_URL` for MinIO support | `"S3_ENDPOINT_URL" in content` of `config.py` | T-23 (`test_minio_endpoint_url_in_settings`) |

---

## 7. Definition of Done (DoD)

- [ ] All 23 Completeness Criteria verified by `test_add_s3_storage.py`
- [ ] `add_s3_storage.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_s3_storage.py` detects `"S3Client"` fingerprint in `app/storage/client.py` and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified` and no filesystem writes
- [ ] `import boto3` appears INSIDE `S3Client.__init__` body — never at module level
- [ ] `generate_key` produces `{prefix}/{uuid4}/{safe_name}` format; `replace("..", "")` and `lstrip("/")` applied to `safe_name`
- [ ] `_validate_content_type` raises HTTP 415 before `generate_presigned_url` when content type is not in whitelist
- [ ] `UploadSizeMiddleware.dispatch` checks `Content-Length` header and returns 413 before consuming body
- [ ] `S3_ENDPOINT_URL` is conditionally passed to `boto3.client("s3", **kwargs)` for MinIO support
- [ ] `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` so fields land inside `Settings` class body
- [ ] `_patch_requirements` adds `boto3>=1.35.0` when absent
- [ ] `_patch_routes_init` idempotently inserts storage router import and `include_router` call
- [ ] `StorageConfig` is a `@dataclass(frozen=True)` with `from_settings()` classmethod
- [ ] `app/storage/__init__.py` exports `S3Client`, `StorageConfig`, `get_s3_client` in `__all__`
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-S3-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"S3Client" in client_file.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-S3-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any `Path.write_text` call | T-03 |
| INV-S3-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: _assert_parses(p)` | T-06, T-20 |
| INV-S3-04 | `boto3` MUST be imported lazily inside `S3Client.__init__` — never at module level | `_S3_CLIENT_TEMPLATE` places `import boto3` inside the `__init__` body; top-level import AST check verifies absence | T-14 |
| INV-S3-05 | Object keys MUST use `{prefix}/{uuid4}/{sanitised_filename}` format | `generate_key` emits `f"{key_prefix}/{uuid.uuid4()}/{safe_name}"` where `safe_name = filename.replace("..", "").lstrip("/")` | T-15 |
| INV-S3-06 | Content-type MUST be validated against the whitelist before presigning | `create_upload_url` calls `_validate_content_type(body.content_type)` as the first statement | T-16 |
| INV-S3-07 | Upload-size enforcement MUST happen at middleware level (before body is consumed) | `UploadSizeMiddleware.dispatch` reads `Content-Length` header, returns 413 without calling `call_next` when exceeded | T-17 |
| INV-S3-08 | `S3_*` settings MUST live inside `class Settings` body (pydantic-settings binding) | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-S3-09 | MinIO MUST be supported via `S3_ENDPOINT_URL` | `S3Client.__init__` conditionally includes `endpoint_url` in boto3 kwargs when `settings.S3_ENDPOINT_URL` is non-empty | T-08, T-23 |
| INV-S3-10 | `get_s3_client()` MUST return a singleton | Module-level `_s3_client_singleton` variable; singleton is created lazily on first call | T-10, T-21 |
| INV-S3-11 | `StorageConfig` MUST be a frozen dataclass | `@dataclass(frozen=True)` decorator prevents mutation after construction | T-22 |
| INV-S3-12 | `app/storage/__init__.py` MUST re-export `S3Client` and `get_s3_client` | `_STORAGE_INIT_TEMPLATE` emits `from app.storage.client import S3Client, get_s3_client` and `__all__` | T-21 |
| INV-S3-13 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on success, no_op, dry_run, and error branches | T-18 |
| INV-S3-14 | `next_steps` MUST reference boto3 installation and bucket configuration | Hard-coded strings in the `success` branch of `add_s3_storage` include `pip install -r requirements.txt` and S3 env var guidance | T-19 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install S3 storage into a clean FastAPI project**
- **As a** backend engineer who needs file uploads
- **I want** to run one tool call and get production-grade storage scaffolding
- **So that** I never buffer binary data through the API server
- **Given:** A FastAPI project with `app/core/config.py` and `requirements.txt`
- **When:** `add_s3_storage(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-S3-01)
  - `files_created` contains ≥ 5 Python files (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/storage/client.py` already contains `S3Client`
- **When:** `add_s3_storage(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-S3-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-S3-03)
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing to a shared codebase
- **Given:** Fresh FastAPI fixture project
- **When:** `add_s3_storage(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-S3-02)
  - Verified by T-03

**US-04: FastAPI process boots without boto3 installed**
- **As a** developer on a machine without boto3 in the virtualenv
- **I want** `uvicorn app.main:app` to work even before `pip install boto3`
- **So that** I can test the HTTP tier independently of the storage integration
- **Given:** `S3Client.__init__` uses a lazy import pattern
- **When:** FastAPI process boots
- **Then:**
  - `import boto3` is inside `__init__` — not at module level (INV-S3-04)
  - `get_s3_client()` is never called at import time
  - Verified by T-14

**US-05: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it in a PR
- **Given:** Tool just emitted `client.py`, `config.py`, `middleware.py`, `routes/storage.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef` / `AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

### 9.2 Presigned URL flow (US-06 .. US-10)

**US-06: Request a presigned upload URL**
- **As a** frontend developer
- **I want** `POST /storage/upload` to return a URL I PUT directly to
- **So that** files bypass the API server completely
- **Given:** `create_upload_url` validates content type and generates a key
- **When:** `POST /api/v1/storage/upload` with `{"filename": "photo.jpg", "content_type": "image/jpeg"}`
- **Then:**
  - Response is `{"upload_url": "https://...", "key": "uploads/uuid/photo.jpg", "expires_in": 3600}`
  - Client PUTs to `upload_url` with `Content-Type: image/jpeg` directly to S3
  - Verified by T-12

**US-07: Request a presigned download URL**
- **As a** frontend developer
- **I want** `GET /storage/{key}` to return a URL for direct download
- **So that** download traffic does not pass through the API server
- **Given:** Object at `key` exists in the bucket
- **When:** `GET /api/v1/storage/uploads/abc/photo.jpg`
- **Then:**
  - Response is `{"download_url": "https://...", "key": "...", "expires_in": 3600}`
  - Client GETs from `download_url` directly from S3
  - Verified by T-12

**US-08: Delete an object**
- **As a** user who deleted their profile photo
- **I want** `DELETE /storage/{key}` to remove the object from the bucket
- **So that** I can enforce user data deletion for GDPR compliance
- **Given:** Object at `key` exists in the bucket
- **When:** `DELETE /api/v1/storage/uploads/abc/photo.jpg`
- **Then:**
  - `S3Client.delete_object(key)` is called; object removed from bucket
  - Response is 204 No Content
  - Verified by T-12

**US-09: Blocked disallowed content types**
- **As a** security engineer
- **I want** `POST /storage/upload` with `content_type="application/x-executable"` to fail
- **So that** attackers cannot upload binaries that get served from the CDN
- **Given:** `settings.S3_ALLOWED_CONTENT_TYPES` does not include the type
- **When:** `POST /api/v1/storage/upload` with `content_type="application/x-executable"`
- **Then:**
  - `_validate_content_type` raises `HTTPException(415, "Content-Type '...' is not allowed")`
  - No presigned URL is generated; no S3 API call is made
  - Verified by T-16 (INV-S3-06)

**US-10: Oversized upload rejected at middleware**
- **As an** API server under a 1 Gbps NIC
- **I want** a 2 GB upload attempt to be rejected at the header level
- **So that** the request body is never read into memory
- **Given:** `UploadSizeMiddleware` is installed with `max_size = settings.S3_MAX_UPLOAD_SIZE_BYTES`
- **When:** Request arrives with `Content-Length: 2147483648`
- **Then:**
  - `dispatch` returns `Response(status_code=413)` before calling `call_next`
  - No handler receives the request body
  - Verified by T-17 (INV-S3-07)

### 9.3 Key generation and security (US-11 .. US-15)

**US-11: Keys prevent filename collisions**
- **As a** multi-user application
- **I want** two users uploading `resume.pdf` to get different keys
- **So that** their files do not overwrite each other
- **Given:** `generate_key` incorporates `uuid.uuid4()`
- **When:** Two calls with `filename="resume.pdf"` and the same prefix
- **Then:**
  - Both return keys of form `uploads/{uuid1}/resume.pdf` and `uploads/{uuid2}/resume.pdf`
  - The UUID segments are different (collision probability negligible)
  - Verified by T-15 (INV-S3-05)

**US-12: Keys are path-traversal-safe**
- **As a** security reviewer
- **I want** a filename of `../../etc/passwd` to be sanitised
- **So that** the key does not escape the designated prefix
- **Given:** `generate_key` applies `filename.replace("..", "").lstrip("/")`
- **When:** `generate_key("../../etc/passwd")`
- **Then:**
  - `safe_name` is `"/etc/passwd"` → `"etc/passwd"` (dots removed, then leading slash stripped)
  - Key is `uploads/{uuid}/etc/passwd` — no traversal possible
  - Verified by T-15 (INV-S3-05)

**US-13: Custom key prefix per upload**
- **As a** developer scoping uploads by feature area
- **I want** `POST /storage/upload` with `"prefix": "avatars"` to generate an `avatars/{uuid}/photo.png` key
- **So that** I can organise bucket contents without a separate route
- **Given:** `UploadRequest.prefix` is forwarded to `generate_key(body.filename, prefix=body.prefix)`
- **When:** Request body includes `"prefix": "avatars"`
- **Then:**
  - Key is `avatars/{uuid}/{filename}`, not `uploads/{uuid}/{filename}`
  - Verified by T-15

**US-14: MinIO works as a drop-in for local development**
- **As a** developer running MinIO in Docker
- **I want** to set `S3_ENDPOINT_URL=http://localhost:9000` in `.env`
- **So that** I do not need an AWS account during development
- **Given:** `S3Client.__init__` passes `endpoint_url` to boto3 when `settings.S3_ENDPOINT_URL` is non-empty
- **When:** `S3_ENDPOINT_URL=http://localhost:9000` and MinIO is running
- **Then:**
  - boto3 targets `http://localhost:9000` instead of `https://s3.amazonaws.com`
  - Presigned URLs point to `http://localhost:9000/...`
  - Verified by T-08, T-23 (INV-S3-09)

**US-15: Presigned URL expiration is configurable**
- **As a** compliance team requiring short-lived URLs
- **I want** to set `S3_PRESIGNED_URL_EXPIRATION=300` in `.env`
- **So that** URLs expire in 5 minutes rather than 1 hour
- **Given:** `presigned_upload_url` and `presigned_download_url` read `settings.S3_PRESIGNED_URL_EXPIRATION`
- **When:** `S3_PRESIGNED_URL_EXPIRATION=300` is set
- **Then:**
  - `expires_in=300` appears in `UploadResponse` and `DownloadResponse`
  - boto3 passes `ExpiresIn=300` to `generate_presigned_url`

### 9.4 Configuration and operator experience (US-16 .. US-20)

**US-16: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `S3_BUCKET_NAME=my-production-bucket` in `.env` to take effect
- **So that** I do not rebuild images for bucket changes
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `S3_BUCKET_NAME` inside `class Settings` picks up env var (INV-S3-08)
  - Fields anchored on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
  - Verified by T-08

**US-17: `requirements.txt` gets boto3**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `boto3>=1.35.0` to appear
- **So that** `S3Client.__init__` can actually import boto3
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `boto3>=` (idempotent: only appended if absent)
  - Verified by T-09

**US-18: Storage router is wired into the API**
- **As a** developer who just ran the tool
- **I want** `GET /api/v1/storage/...` to be reachable without manual wiring
- **So that** I can test the routes immediately
- **Given:** `_patch_routes_init` inserts import and `include_router` into `app/routes/__init__.py`
- **When:** FastAPI app boots
- **Then:**
  - `storage_router` is included in `api_router`
  - Routes are accessible at `/api/v1/storage/*`
  - Verified by T-13

**US-19: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include boto3 install and bucket setup
- **So that** I do not forget to create the S3 bucket and set CORS
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `pip install -r requirements.txt` and bucket configuration guidance
  - Verified by T-19 (INV-S3-14)

**US-20: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the step budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-S3-13)
  - Verified by T-18

---

## 10. Test Plan

All 23 tests live in `adapt/extend/infrastructure/test_add_s3_storage.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `s3_t01` | `add_s3_storage(ToolInput(project_dir))` | `result.status == "success"` (INV-S3-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `s3_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` (INV-S3-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `s3_t03`; snapshot all `.py` | `add_s3_storage(ToolInput(dry_run=True))` | `status == "success"`; empty create/modify lists; byte-identical filesystem (INV-S3-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `s3_t04` | Run tool | `len(py_created) >= 5`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `s3_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-09)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `s3_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-S3-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `s3_t07`; run tool | AST walk over `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `s3_t08`; run tool | Read `app/core/config.py` | Contains `S3_BUCKET_NAME`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PRESIGNED_URL_EXPIRATION`; `S3_BUCKET_NAME` line starts with 4-space indent (INV-S3-08, CC-08) |
| T-09 | `test_requirements_patched` | Fixture `s3_t09`; run tool | Read `requirements.txt` | Contains `"boto3>="` (CC-09) |

### 10.3 Category C — Domain-specific modules (T-10 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-10 | `test_s3_client_created` | Fixture `s3_t10`; run tool | Read `app/storage/client.py` | File exists; contains `"class S3Client"` (INV-S3-10, CC-10) |
| T-11 | `test_presigned_url_helpers` | Fixture `s3_t11`; run tool | Read `app/storage/client.py` | Contains `"presigned_upload_url"` and `"presigned_download_url"` (CC-11) |
| T-12 | `test_storage_routes_created` | Fixture `s3_t12`; run tool | Read `app/api/routes/storage.py` | File exists; contains `"/upload"`, `"delete"` (lower), `"download"` (lower) (CC-12) |
| T-13 | `test_routes_registered` | Fixture `s3_t13`; run tool | Read `app/routes/__init__.py` if exists | Contains `"storage"` (case-insensitive) (INV-S3-12, CC-13) |
| T-14 | `test_lazy_boto3_import` | Fixture `s3_t14`; run tool | Parse `client.py` AST for top-level imports | `"boto3"` absent from top-level imports; `"import boto3"` present in file body (INV-S3-04, CC-14) |
| T-15 | `test_key_generation_pattern` | Fixture `s3_t15`; run tool | Read `app/storage/client.py` | `"generate_key"` in content; `"uuid"` in content (lower); `"{prefix}"` or `"key_prefix"` in content (INV-S3-05, CC-15) |
| T-16 | `test_content_type_validation` | Fixture `s3_t16`; run tool | Read `app/api/routes/storage.py` | `"content_type"` in content; `"415"` or `"UNSUPPORTED_MEDIA_TYPE"` in content; `"S3_ALLOWED_CONTENT_TYPES"` or `"allowed"` (lower) in content (INV-S3-06, CC-16) |
| T-17 | `test_max_file_size_from_settings` | Fixture `s3_t17`; run tool | Read `app/storage/middleware.py` | File exists; `"S3_MAX_UPLOAD_SIZE_BYTES"` in content; `"413"` in content (INV-S3-07, CC-17) |

### 10.4 Category D — Meta (T-18 .. T-23)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `s3_t18`; run tool | Read `result.execution_time_ms` | `> 0` (INV-S3-13, CC-18) |
| T-19 | `test_next_steps_present` | Fixture `s3_t19`; run tool | Inspect `result.next_steps` | Non-empty; lowercased join contains `"pip"` or `"boto3"` and `"bucket"` or `"s3_bucket_name"` (INV-S3-14, CC-19) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `s3_t20`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-S3-01, INV-S3-03, CC-20) |
| T-21 | `test_storage_package_init_re_exports` | Fixture `s3_t21`; run tool | Read `app/storage/__init__.py` | File exists; `"S3Client"` in content; `"get_s3_client"` in content (INV-S3-12, CC-21) |
| T-22 | `test_storage_config_dataclass_created` | Fixture `s3_t22`; run tool | Read `app/storage/config.py` | File exists; `"StorageConfig"` in content; `"from_settings"` in content (INV-S3-11, CC-22) |
| T-23 | `test_minio_endpoint_url_in_settings` | Fixture `s3_t23`; run tool | Read `app/core/config.py` | `"S3_ENDPOINT_URL"` in content (INV-S3-09, CC-23) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_s3_storage.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_s3_storage.py
```

Target: 23/23 passed, 0 failed. The standalone runner prints `23/23 tests passed`.

---

## 11. Interaction Matrix

How `add_s3_storage` composes with other SKILL-001 tools. Tool IDs below match the `specs/` directory.

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_file_upload` (TOOL-003) | Yes | ⚠️ Conflict — use one or the other | TOOL-003 installs `UploadFile`-based proxied upload; TOOL-060 replaces that with presigned URLs; installing both creates duplicate routes at `/upload` |
| `add_multi_tenancy` (TOOL-008) | Yes | ✅ Compatible — tenancy runs FIRST | When tenancy is installed, `generate_key` should use `{tenant_id}/{prefix}/{uuid}/{filename}` to scope objects per tenant; update `UploadRequest` to include `tenant_id` |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | Adds `require("storage:upload")`, `require("storage:download")`, `require("storage:delete")` to the three routes; current version has no auth gate on storage routes (by design — presigned URLs are scope-limited) |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API key holders can generate presigned URLs for programmatic upload pipelines |
| `add_oauth2_provider` (TOOL-011) | No | ✅ Compatible | OAuth2 token holders access presigned-URL routes via the same dependency chain |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat — audit should wrap route handlers | `create_upload_url`, `create_download_url`, `delete_object` should emit audit entries with `user_id`, `key`, and action; do NOT log presigned URL values (they contain signatures) |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | S3 objects are deleted immediately via `delete_object`; if soft-delete semantics are needed, store object metadata in a DB table with `deleted_at` and defer the actual S3 deletion to a scheduled task |
| `add_celery_beat` (TOOL-059) | No | ✅ Compatible | `cleanup_expired` task in TOOL-059 can list objects older than N days via boto3 `list_objects_v2` and call `S3Client.delete_object` to enforce storage lifecycle; avoids relying solely on S3 lifecycle rules |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | arq tasks can call `get_s3_client().delete_object(key)` for deferred deletion; use `enqueue("cleanup_s3_task", keys=[...])` to batch deletions |
| `add_cache_layer` (TOOL-021) | No | ✅ Compatible | Presigned download URLs can be cached by `key` for `presigned_url_expiration / 2` seconds to avoid redundant `generate_presigned_url` HMAC computations |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | Upload complete events (`object.uploaded`, `object.deleted`) can be published after key generation or after deletion to trigger downstream processing |
| `add_webhook_sender` (TOOL-015) | No | ✅ Compatible | Webhook payloads can include presigned download URLs so subscribers fetch the binary asset directly from S3 without an API server hop |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | If object metadata is persisted to a relational table (key, owner, size, created_at), list endpoints can apply cursor pagination by `created_at DESC` |
| `add_data_export` (TOOL-006) | No | ⚠️ Caveat | Data exports that include user-uploaded files should generate presigned download URLs, not bundle the raw bytes; PII in filenames must be scrubbed before URL generation |
| `add_search` (TOOL-004) | No | ⚠️ Caveat | Full-text search over uploaded content (OCR, PDF extraction) should run in a background task (TOOL-059 or TOOL-053) after the upload is confirmed, not inline in the upload route |
| `add_rate_limiting` (TOOL-057) | No | ✅ Compatible | Rate-limit `POST /storage/upload` by user ID to prevent presigned URL generation abuse; presigned URLs themselves are self-limiting (short TTL, scoped to one key) |
| `add_feature_flags` (TOOL-009) | No | ✅ Compatible | Allowed content-type list and max upload size can be gated behind feature flags for gradual rollout |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | If object metadata is persisted, the admin panel can render a file management view with `ModelAdmin` for `ObjectMetadata` |
| `generate_sdk` (TOOL-047) | No | ✅ Compatible | Generated SDK clients include typed wrappers for `POST /storage/upload`, `GET /storage/{key}`, `DELETE /storage/{key}` with `UploadRequest` / `UploadResponse` / `DownloadResponse` models |
| `add_circuit_breaker` (TOOL-022) | No | ✅ Compatible | `S3Client` methods that call boto3 (`presigned_upload_url`, `presigned_download_url`, `delete_object`) can be wrapped in a circuit breaker to handle S3 / MinIO outages gracefully |

**Conflicts:** `add_file_upload` (TOOL-003) and `add_s3_storage` (TOOL-060) both address file upload functionality; they are mutually exclusive. Choose TOOL-060 for all new projects; use TOOL-003 only for small files (< 1 MB) that must be validated server-side before storage.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/routes/__init__.py \
  requirements.txt

rm -rf \
  app/storage/ \
  app/api/routes/storage.py
```

### 12.2 No database rollback required

`add_s3_storage` does not create any database tables or Alembic migrations. There is no schema rollback step.

### 12.3 S3 data preservation (before rollback)

If the application has been in production with objects already uploaded, do NOT delete the bucket. Objects in S3 persist independently of the code. Rollback only removes the API routes — existing presigned URLs remain valid until their TTL expires.

To delete all objects if you need a clean slate (development only):

```bash
aws s3 rm s3://<bucket> --recursive
# or via MinIO:
mc rm --recursive --force myminio/<bucket>
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

Because `_assert_parses` runs at the end of the tool's success path, a mid-execution failure may leave partially-written files. The tool writes files one at a time; `git checkout HEAD --` on modified paths plus `rm` on newly-created paths restores the project.

### 12.5 Emergency: boto3 / S3 outage

1. `POST /storage/upload` and `GET /storage/{key}` will return 500 when `boto3.client.generate_presigned_url` fails (boto3 raises on network errors to AWS).
2. Disable storage routes: `mv app/api/routes/storage.py app/api/routes/storage.py.disabled` and comment out `include_router(storage_router)` in `app/routes/__init__.py`.
3. Restart FastAPI — the API tier continues serving all other routes.
4. On S3 restore, revert the disable steps and restart.
5. `UploadSizeMiddleware` is applied globally — if it interferes with other routes, remove it from `app/main.py` temporarily during the outage.

### 12.6 Uninstall validator

After rollback, verify:

```bash
test ! -d app/storage || (echo "app/storage still present" && exit 1)
test ! -f app/api/routes/storage.py || (echo "storage.py still present" && exit 1)
grep -q "S3_BUCKET_NAME" app/core/config.py && echo "config still patched" && exit 1
grep -q "boto3" requirements.txt && echo "requirements.txt still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing prerequisites (`CONFIG_SETTINGS` or `REQUIREMENTS_TXT`) | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | Tool runs on a project with `app/storage/client.py` already containing `S3Client` | Early return `status="no_op"` with note `"S3Client already present in app/storage/client.py — S3 storage is already installed, skipped."` — zero file writes |
| EC-04 | Tool runs with `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-S3-02) |
| EC-05 | `app/core/config.py` already contains `S3_BUCKET_NAME` | `_patch_config` early-returns (`"S3_BUCKET_NAME" in src`); no duplicate block appended |
| EC-06 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; if also missing, appends at EOF (valid Python; fields land at module scope) |
| EC-07 | `requirements.txt` already contains `boto3` | `_patch_requirements` early-returns (`"boto3" in src`); no duplicate line appended |
| EC-08 | `app/routes/__init__.py` does not exist | `_patch_routes_init` step is conditional on `routes_init.exists()`; silently skipped; router must be registered manually |
| EC-09 | `app/routes/__init__.py` already contains storage router import | `_register_router_in_routes_init` early-returns (`import_line in src`); no duplicate import or `include_router` call |
| EC-10 | `app/api/routes/` directory does not exist | `_write_storage_routes` calls `routes_dir.mkdir(parents=True, exist_ok=True)` before writing |
| EC-11 | `app/storage/` directory does not exist | All `_write_*` helpers call `dest.parent.mkdir(parents=True, exist_ok=True)` — created automatically |
| EC-12 | Generated `client.py` fails `ast.parse` | `_assert_parses` raises `SyntaxError` with the file path; partial files remain on disk (use rollback 12.4) |
| EC-13 | `S3_ALLOWED_CONTENT_TYPES` is set to an empty list in settings | `_validate_content_type` checks `if allowed and ...`; empty list bypasses validation — all content types are accepted |
| EC-14 | `Content-Length` header is absent (chunked transfer encoding) | `UploadSizeMiddleware.dispatch` checks `if content_length_str is not None`; absent header skips size enforcement — object is uploaded without size guarantee |
| EC-15 | `Content-Length` header is present but non-numeric | `int(content_length_str)` raises `ValueError`; caught → `content_length = 0`; size check does not trigger |
| EC-16 | Filename contains OS path separators (e.g. `photos/summer/beach.jpg`) | `safe_name = filename.replace("..", "").lstrip("/")` strips leading slash; slashes within the name are preserved — key is `uploads/{uuid}/photos/summer/beach.jpg` |
| EC-17 | `settings.S3_ENDPOINT_URL` is empty string | `if settings.S3_ENDPOINT_URL:` is falsy; `endpoint_url` is NOT passed to boto3; defaults to AWS endpoints |
| EC-18 | `settings.S3_ACCESS_KEY_ID` is empty string | `settings.S3_ACCESS_KEY_ID or None` evaluates to `None`; boto3 falls back to instance profile / environment credential chain |
| EC-19 | boto3 is not installed at tool run time | Tool writes all files successfully; `boto3` import is never triggered by the tool itself; `_assert_parses` parses the template without importing it |
| EC-20 | Very large `S3_ALLOWED_CONTENT_TYPES` list | `_validate_content_type` iterates `allowed`; O(n) check on list; no performance issue for typical whitelist sizes (< 100 types) |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 23 Completeness Criteria verified via `test_add_s3_storage.py` passing
2. ✅ `test_add_s3_storage.py` reports `23/23 tests passed` via both pytest and standalone runner
3. ✅ Tool execution time < 5 s measured on reference hardware
4. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-S3-01)
5. ✅ `dry_run=True` produces zero filesystem writes (INV-S3-02)
6. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-S3-03)
7. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
8. ✅ `S3_*` settings live inside `class Settings` body with 4-space indentation (INV-S3-08)
9. ✅ `import boto3` appears inside `S3Client.__init__` — never at module level (INV-S3-04)
10. ✅ `generate_key` produces `{prefix}/{uuid4}/{sanitised_filename}` — collision-safe, path-traversal-safe (INV-S3-05)
11. ✅ `_validate_content_type` raises HTTP 415 before presigned URL generation for disallowed types (INV-S3-06)
12. ✅ `UploadSizeMiddleware` returns HTTP 413 without consuming the request body (INV-S3-07)
13. ✅ `S3_ENDPOINT_URL` enables MinIO as a drop-in alternative to AWS (INV-S3-09)
14. ✅ `StorageConfig` is a frozen dataclass with `from_settings()` classmethod (INV-S3-11)
15. ✅ `next_steps` includes boto3 install, bucket configuration, and CORS guidance (INV-S3-14)
16. ✅ Developer successfully calls `POST /storage/upload`, receives `upload_url`, PUTs file directly to S3, calls `GET /storage/{key}` and `DELETE /storage/{key}`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(CONFIG_SETTINGS, REQUIREMENTS_TXT)` passes; auto-scaffold if `not inp.dry_run`
- [ ] `app/storage/client.py` does NOT contain `"S3Client"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Storage package

- [ ] Write `app/storage/__init__.py` via `_write_storage_init`
  - [ ] Imports `S3Client`, `get_s3_client` from `app.storage.client`
  - [ ] Imports `StorageConfig` from `app.storage.config`
  - [ ] Exports all three in `__all__`

### 15.3 S3 client

- [ ] Write `app/storage/client.py` via `_write_s3_client` using `_S3_CLIENT_TEMPLATE`
  - [ ] `import boto3` INSIDE `__init__` body (lazy)
  - [ ] `kwargs` dict conditionally includes `endpoint_url` when `settings.S3_ENDPOINT_URL` is non-empty
  - [ ] `aws_access_key_id` and `aws_secret_access_key` use `or None` fallback for empty strings
  - [ ] `generate_key` applies `replace("..", "").lstrip("/")` before embedding filename
  - [ ] `presigned_upload_url` passes `HttpMethod="PUT"` to `generate_presigned_url`
  - [ ] `presigned_download_url` uses `"get_object"` action
  - [ ] `delete_object` calls `self._client.delete_object(Bucket=..., Key=...)`
  - [ ] `get_s3_client()` uses module-level `_s3_client_singleton` with lazy init

### 15.4 StorageConfig

- [ ] Write `app/storage/config.py` via `_write_storage_config` using `_STORAGE_CONFIG_TEMPLATE`
  - [ ] `@dataclass(frozen=True)` decorator
  - [ ] All eight fields typed: `bucket_name`, `region`, `endpoint_url`, `presigned_url_expiration`, `max_upload_size_bytes`, `allowed_content_types`, `key_prefix`
  - [ ] `from_settings()` classmethod reads all fields from `settings.*`

### 15.5 Upload-size middleware

- [ ] Write `app/storage/middleware.py` via `_write_storage_middleware` using `_STORAGE_MIDDLEWARE_TEMPLATE`
  - [ ] Extends `BaseHTTPMiddleware`
  - [ ] `max_size` defaults to `settings.S3_MAX_UPLOAD_SIZE_BYTES`
  - [ ] `dispatch` checks `request.method in ("PUT", "POST")`
  - [ ] Returns `Response(status_code=413)` when `content_length > self.max_size`
  - [ ] `ValueError` on non-numeric `Content-Length` → `content_length = 0` (no rejection)

### 15.6 REST routes

- [ ] Write `app/api/routes/storage.py` via `_write_storage_routes` using `_STORAGE_ROUTES_TEMPLATE`
  - [ ] `router = APIRouter(prefix="/storage", tags=["storage"])`
  - [ ] `UploadRequest`: `filename` (1-255 chars), `content_type` (min 1), `prefix` (max 200, default "")
  - [ ] `UploadResponse`: `upload_url`, `key`, `expires_in`
  - [ ] `DownloadResponse`: `download_url`, `key`, `expires_in`
  - [ ] `_validate_content_type` raises HTTP 415 when type not in `settings.S3_ALLOWED_CONTENT_TYPES` and list is non-empty
  - [ ] `POST /upload` calls `_validate_content_type` FIRST, then `generate_key`, then `presigned_upload_url`
  - [ ] `GET /{key:path}` returns `DownloadResponse`
  - [ ] `DELETE /{key:path}` returns 204 No Content

### 15.7 Config patch

- [ ] Early-return if `"S3_BUCKET_NAME" in src`
- [ ] Block emits all eight S3 fields with defaults
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.8 Routes init patch

- [ ] Conditional on `routes_init.exists()`
- [ ] Early-return if `import_line in src`
- [ ] Insert `from app.api.routes.storage import router as storage_router` after last `from app.` import
- [ ] Insert `api_router.include_router(storage_router)` after last `include_router` call
- [ ] Preserve trailing newline

### 15.9 Requirements patch

- [ ] Early-return if `"boto3" in src`
- [ ] Append `boto3>=1.35.0\n` with trailing newline handling

### 15.10 Validation

- [ ] Loop over `files_created`; for every `.py` call `_assert_parses(p)`
- [ ] `_assert_parses` raises `SyntaxError` with file path on failure

### 15.11 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain: lazy boto3, presigned URL pattern, no binary buffering, path-traversal protection, MinIO support
- [ ] `next_steps` contain: `pip install -r requirements.txt`, env var setup (bucket, region, keys), MinIO config, bucket creation, CORS setup, restart reminder, test example

### 15.12 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files, the presigned URL rationale, and all security guarantees
- [ ] `add_s3_storage` docstring documents `inp` parameter and all return fields

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/storage/__init__.py",
    "/tmp/fixture/app/storage/client.py",
    "/tmp/fixture/app/storage/config.py",
    "/tmp/fixture/app/storage/middleware.py",
    "/tmp/fixture/app/api/routes/storage.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "S3/MinIO storage added: lazy boto3 wrapper, StorageConfig, UploadSizeMiddleware,",
    "POST /storage/upload (presigned PUT URL), GET /storage/{key} (presigned GET URL),",
    "DELETE /storage/{key} — all routed through app/api/routes/storage.py.",
    "Files go directly to S3/MinIO via presigned URLs — the API never buffers binary data.",
    "Object keys are generated as {prefix}/{uuid4}/{filename} to prevent collisions and path traversal.",
    "Set S3_ENDPOINT_URL to your MinIO address for local/self-hosted usage; omit for AWS.",
    "boto3 is imported lazily inside S3Client — the app boots without boto3 installed."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # installs boto3",
    "Set S3_BUCKET_NAME, S3_REGION, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY in .env.",
    "For MinIO: also set S3_ENDPOINT_URL=http://localhost:9000",
    "Create the bucket: aws s3 mb s3://<bucket>  (or via MinIO console)",
    "Configure bucket CORS to allow PUT from your frontend origin.",
    "Restart the FastAPI app so /storage/* routes are loaded.",
    "Test: POST /api/v1/storage/upload with {\"filename\": \"test.png\", \"content_type\": \"image/png\"} to receive a presigned upload URL."
  ],
  "execution_time_ms": 87
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "S3Client already present in app/storage/client.py — S3 storage is already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 2
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/storage/__init__.py, app/storage/client.py,",
    "         app/storage/config.py, app/storage/middleware.py,",
    "         and app/api/routes/storage.py.",
    "[dry_run] Would patch app/core/config.py with S3_* settings,",
    "         app/routes/__init__.py to register the storage router,",
    "         and requirements.txt with boto3>=1.35.0.",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 1
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing\n  - REQUIREMENTS_TXT: requirements.txt missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 2
}
```

---
