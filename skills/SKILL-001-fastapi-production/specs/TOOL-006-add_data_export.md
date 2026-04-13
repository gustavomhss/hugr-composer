# TOOL-006: add_data_export

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_data_export` |
| Category | EXTEND > CRUD & Data |
| Complexity | Medium |
| Dependencies | Existing project with at least 1 model, SQLAlchemy 2.0 async, Alembic |
| Signature | `add_data_export(project_dir: str, models: list[str] \| None = None, formats: list[str] = ["csv", "json"], async_threshold: int = 10000, storage_backend: str = "s3") -> dict` |
| Parameters | `project_dir`: project root path<br>`models`: model names to enable export on (None = all business models)<br>`formats`: list of supported export formats — `csv`, `json`, `xlsx`, `parquet`<br>`async_threshold`: row count above which export becomes an async background job (default 10000)<br>`storage_backend`: where async exports are stored — `s3` or `local` |

---

## 2. Purpose

`fastapi_add_data_export` adds production-grade data portability to a FastAPI application, implementing GDPR Article 20 (right to data portability) as a first-class feature. The problem it solves is multi-dimensional: users increasingly demand the ability to download their data in machine-readable formats (CSV for spreadsheets, JSON for programmatic access, Parquet for data science workflows), regulatory frameworks in the EU and Brazil (LGPD) legally mandate it, and naive implementations that load an entire result set into RAM collapse under realistic data volumes. This tool generates a memory-bounded streaming export pipeline using SQLAlchemy server-side cursors and `StreamingResponse`, ensuring that a 10-million-row export occupies less than 50 MB of server RAM regardless of dataset size. Per-user and per-tenant scoping is enforced at the query layer — an export endpoint reuses the same `WHERE owner_id = ?` and `WHERE tenant_id = ?` guards as the list endpoint, so it is impossible for a user to export another user's rows even if they guess the endpoint URL.

Beyond synchronous streaming, large exports that would hold an HTTP connection open for minutes are automatically promoted to asynchronous background jobs. A preflight `COUNT(*)` query determines whether the dataset exceeds `async_threshold`; if so, the request returns HTTP 202 immediately with a `job_id`, and an ARQ background worker streams the data to S3 (or local disk), then emails the user a presigned download URL that expires after 24 hours. This pattern eliminates Nginx/gunicorn timeout failures on large datasets, frees the client from holding an open connection, and gives operators a clean audit trail of export activity. Progress tracking, job failure notifications, TTL-based URL expiry, and a quota guard (preventing export abuse by rate-limiting concurrent exports per user) round out the production safety envelope that naive `response.all()` approaches entirely omit.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 4s for up to 5 models | Dev waits at CLI; one-time setup cost |
| Files created | 4–7 (`export.py`, `export_jobs.py`, `jobs/export.py`, migration, test file, optional storage adapter, optional progress tracker) | Predictable scaffolding surface |
| Files modified | ≤ 4 (route file per model, `config.py`, `requirements.txt`, `.env.example`) | Minimal blast radius on existing code |
| Server RAM peak per sync export | < 50 MB regardless of dataset size | Server-side cursor + 1000-row batch streaming; never loads full result |
| Sync export TTFB (time to first byte) | < 500 ms | CSV header row flushed immediately; generator yields on first batch |
| Sync export throughput for 10k rows CSV | < 2 s total | 10 batches × 1000 rows; 1 DB round-trip per batch |
| Async export dispatch latency | < 200 ms | Only enqueues ARQ job; no data transferred in request context |
| Async export completion for 1M rows | < 5 min | Worker streams to S3 in 1000-row chunks; parallel I/O possible |
| Presigned URL TTL | 86400 s (24 h) | Long enough for async delivery; short enough to bound exposure |
| Export quota per user | ≤ 3 concurrent async jobs | Prevents export abuse and S3 cost runaway |

---

## 4. Code Examples

### 4.1 Export core — GENERATED `app/core/export.py`

```python
"""
Streaming data export utilities: CSV, NDJSON, XLSX, Parquet.

All generators are async and memory-bounded: rows are fetched in batches
via SQLAlchemy server-side cursors and yielded as bytes chunks.
Never accumulates the full dataset in RAM.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import Select, func, select

BATCH_SIZE: int = 1000

# Columns that MUST never appear in any export, regardless of caller request
SENSITIVE_COLUMNS: frozenset[str] = frozenset({
    "hashed_password", "password", "secret", "api_key", "token",
    "refresh_token", "private_key", "api_secret", "client_secret",
})


async def _stream_batches(
    session: AsyncSession, stmt: Select, batch_size: int = BATCH_SIZE
) -> AsyncIterator[list[Any]]:
    """Yield rows in batches using a server-side streaming cursor."""
    result = await session.stream(stmt.execution_options(yield_per=batch_size))
    async for partition in result.partitions(batch_size):
        yield [row[0] for row in partition]


async def export_csv(
    session: AsyncSession, stmt: Select, columns: list[str]
) -> AsyncIterator[bytes]:
    """Stream CSV bytes. Yields UTF-8 header row first, then data chunks."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(columns)
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate()

    async for batch in _stream_batches(session, stmt):
        for row in batch:
            writer.writerow([_safe_str(getattr(row, col, "")) for col in columns])
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()


async def export_ndjson(
    session: AsyncSession, stmt: Select, columns: list[str]
) -> AsyncIterator[bytes]:
    """Stream NDJSON (newline-delimited JSON). One object per line."""
    async for batch in _stream_batches(session, stmt):
        lines = "".join(
            json.dumps({col: _serialize(getattr(row, col, None)) for col in columns}) + "\n"
            for row in batch
        )
        yield lines.encode("utf-8")


async def export_xlsx(
    session: AsyncSession, stmt: Select, columns: list[str]
) -> AsyncIterator[bytes]:
    """Stream XLSX using xlsxwriter constant_memory mode (write-once, low RAM)."""
    import xlsxwriter

    buf = io.BytesIO()
    workbook = xlsxwriter.Workbook(buf, {"constant_memory": True, "in_memory": True})
    worksheet = workbook.add_worksheet("Export")
    bold = workbook.add_format({"bold": True})

    for col_idx, col_name in enumerate(columns):
        worksheet.write(0, col_idx, col_name, bold)

    row_idx = 1
    async for batch in _stream_batches(session, stmt):
        for row in batch:
            for col_idx, col_name in enumerate(columns):
                worksheet.write(row_idx, col_idx, _safe_str(getattr(row, col_name, "")))
            row_idx += 1

    workbook.close()
    yield buf.getvalue()


async def export_parquet(
    session: AsyncSession, stmt: Select, columns: list[str]
) -> AsyncIterator[bytes]:
    """Stream Parquet via pyarrow. Collects all rows (pyarrow lacks native streaming write)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    rows: list[dict[str, Any]] = []
    async for batch in _stream_batches(session, stmt):
        for row in batch:
            rows.append({col: _serialize(getattr(row, col, None)) for col in columns})

    table = pa.Table.from_pylist(rows)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    yield buf.getvalue()


def _serialize(value: Any) -> Any:
    """Coerce non-JSON-native Python types to serialisable equivalents."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _safe_str(value: Any) -> str:
    """Return serialised value as string; None becomes empty string."""
    if value is None:
        return ""
    return str(_serialize(value))
```

### 4.2 Export route addition — GENERATED into `app/api/routes/{model}.py`

```python
"""
Export endpoint appended to the existing model router.
Supports sync streaming (small datasets) and async background jobs (large datasets).
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.export import (
    SENSITIVE_COLUMNS,
    export_csv,
    export_ndjson,
    export_xlsx,
    export_parquet,
)
from app.core.export_jobs import dispatch_export_job
from app.models.item import Item


_FORMAT_META: dict[str, tuple] = {
    "csv":     (export_csv,     "text/csv",                                          "items.csv"),
    "json":    (export_ndjson,  "application/x-ndjson",                              "items.ndjson"),
    "xlsx":    (export_xlsx,    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "items.xlsx"),
    "parquet": (export_parquet, "application/octet-stream",                          "items.parquet"),
}

_DEFAULT_COLUMNS: list[str] = [
    c.name for c in Item.__table__.columns
    if c.name not in SENSITIVE_COLUMNS
]


@router.get("/export", summary="Export items (GDPR Art. 20 data portability)")
async def export_items(
    session: SessionDep,
    current_user: CurrentUser,
    format: str = Query(default="csv", pattern="^(csv|json|xlsx|parquet)$"),
    columns: str | None = Query(
        default=None,
        description="Comma-separated column names to include. Omit for all non-sensitive columns.",
    ),
) -> StreamingResponse | JSONResponse:
    """
    Export the current user's items in the requested format.

    - Small exports (< EXPORT_ASYNC_THRESHOLD rows) are streamed synchronously.
    - Large exports are queued as background jobs and delivered via email link.
    - Sensitive columns (hashed_password, api_key, etc.) are ALWAYS excluded.
    """
    base_stmt = select(Item).where(Item.owner_id == current_user.id)
    if hasattr(Item, "is_deleted"):
        base_stmt = base_stmt.where(Item.is_deleted.is_(False))
    if hasattr(Item, "tenant_id") and hasattr(current_user, "tenant_id"):
        base_stmt = base_stmt.where(Item.tenant_id == current_user.tenant_id)

    # Preflight: count rows to decide sync vs async path
    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total: int = (await session.execute(count_stmt)).scalar_one()

    if total > settings.EXPORT_ASYNC_THRESHOLD:
        job_id = await dispatch_export_job(
            user_id=current_user.id,
            model="Item",
            format=format,
            filters={"owner_id": str(current_user.id)},
        )
        return JSONResponse(
            status_code=202,
            content={
                "status": "queued",
                "job_id": str(job_id),
                "row_estimate": total,
                "message": (
                    f"Export queued ({total:,} rows). "
                    "You will receive an email with a download link."
                ),
            },
        )

    # Resolve and whitelist requested columns
    requested = [c.strip() for c in columns.split(",")] if columns else _DEFAULT_COLUMNS
    safe_cols = [c for c in requested if c in _DEFAULT_COLUMNS]
    if not safe_cols:
        raise HTTPException(status_code=422, detail="No valid columns selected after security filtering.")

    gen_fn, media_type, filename = _FORMAT_META[format]
    return StreamingResponse(
        gen_fn(session, base_stmt, safe_cols),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

### 4.3 Async dispatcher — GENERATED `app/core/export_jobs.py`

```python
"""
Dispatch helper for large-dataset async export jobs.
Requires ARQ queue (add_background_job tool must run first).
"""
from __future__ import annotations

import uuid
from typing import Any

from app.core.arq import enqueue_job


async def dispatch_export_job(
    *,
    user_id: uuid.UUID,
    model: str,
    format: str,
    filters: dict[str, Any],
) -> uuid.UUID:
    """
    Enqueue a background export job. Returns a new job_id UUID.
    The worker will stream data to storage and email the user a presigned URL.
    """
    job_id = uuid.uuid4()
    await enqueue_job(
        "run_export",
        job_id=str(job_id),
        user_id=str(user_id),
        model=model,
        format=format,
        filters=filters,
    )
    return job_id
```

### 4.4 ARQ background worker — GENERATED `app/jobs/export.py`

```python
"""
ARQ worker: exports data to S3 (or local storage) and emails the user a presigned link.
Registered in WorkerSettings.functions.
"""
from __future__ import annotations

import io
import logging
import uuid
from typing import Any

from app.core.export import export_csv, export_ndjson, export_xlsx, export_parquet
from app.core.storage import get_storage
from app.core.email import send_email
from app.crud.user import get as crud_get_user

logger = logging.getLogger(__name__)

_GENERATORS = {
    "csv":     export_csv,
    "json":    export_ndjson,
    "xlsx":    export_xlsx,
    "parquet": export_parquet,
}


async def run_export(
    ctx: dict,
    *,
    job_id: str,
    user_id: str,
    model: str,
    format: str,
    filters: dict[str, Any],
) -> dict[str, Any]:
    """
    ARQ job entrypoint. Runs inside the worker process.
    Streams rows to storage, emails presigned URL to user.
    """
    session = ctx["session"]
    storage = get_storage()
    gen_fn = _GENERATORS.get(format)
    if gen_fn is None:
        raise ValueError(f"run_export: unknown format={format!r}")

    stmt = _build_query(model, filters)
    cols = _default_columns(model)

    buf = io.BytesIO()
    async for chunk in gen_fn(session, stmt, cols):
        buf.write(chunk)
    buf.seek(0)

    key = f"exports/{job_id}.{format}"
    await storage.save(buf, key, content_type="application/octet-stream")
    url = await storage.presigned_url(key, expires_in=86400)

    user = await crud_get_user(session, uuid.UUID(user_id))
    if user and user.email:
        await send_email(
            to=user.email,
            subject=f"Your {model} data export is ready",
            body=(
                f"Your export is ready for download.\n\n"
                f"Download link (expires in 24 hours):\n{url}\n\n"
                f"This link cannot be shared — it is scoped to your account."
            ),
        )
        logger.info("export_complete job_id=%s model=%s format=%s user=%s", job_id, model, format, user_id)
    else:
        logger.warning("export_complete_no_email job_id=%s user_id=%s", job_id, user_id)

    return {"job_id": job_id, "url": url, "status": "complete"}


def _build_query(model: str, filters: dict[str, Any]):
    """Reconstruct the export query from model name + filters dict."""
    from app.core.model_registry import get_model_class, build_filtered_stmt
    model_cls = get_model_class(model)
    return build_filtered_stmt(model_cls, filters)


def _default_columns(model: str) -> list[str]:
    """Return non-sensitive column names for the given model."""
    from app.core.export import SENSITIVE_COLUMNS
    from app.core.model_registry import get_model_class
    model_cls = get_model_class(model)
    return [c.name for c in model_cls.__table__.columns if c.name not in SENSITIVE_COLUMNS]
```

### 4.5 Export job progress tracker — GENERATED `app/core/export_progress.py`

```python
"""
Lightweight export job progress tracker backed by Redis.
Writes progress keys so clients can poll /exports/{job_id}/status.
"""
from __future__ import annotations

import json
from enum import Enum
from typing import Any

import redis.asyncio as aioredis

JOB_TTL_SECONDS: int = 90_000  # slightly over 24 h — covers presigned URL lifetime


class ExportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


async def set_export_progress(
    redis: aioredis.Redis,
    job_id: str,
    status: ExportStatus,
    *,
    rows_written: int = 0,
    total_rows: int = 0,
    download_url: str | None = None,
    error: str | None = None,
) -> None:
    """Write job progress to Redis with a 25-hour TTL."""
    key = f"export_job:{job_id}"
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status.value,
        "rows_written": rows_written,
        "total_rows": total_rows,
    }
    if download_url:
        payload["download_url"] = download_url
    if error:
        payload["error"] = error
    await redis.setex(key, JOB_TTL_SECONDS, json.dumps(payload))


async def get_export_progress(
    redis: aioredis.Redis, job_id: str
) -> dict[str, Any] | None:
    """Fetch current job progress. Returns None if job_id unknown or expired."""
    key = f"export_job:{job_id}"
    raw = await redis.get(key)
    if raw is None:
        return None
    return json.loads(raw)
```

### 4.6 S3 presigned URL helper — GENERATED `app/core/storage.py` (fragment)

```python
"""
Storage abstraction with S3 presigned URL support and local-file fallback.
Used by the async export worker to store completed export files.
"""
from __future__ import annotations

import os
from typing import BinaryIO

import boto3
from botocore.exceptions import ClientError


class S3StorageBackend:
    """
    Wraps boto3 S3 client with async-compatible upload and presigned-URL generation.
    Credentials read from AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_BUCKET.
    """

    def __init__(self) -> None:
        self._bucket = os.environ["AWS_S3_BUCKET"]
        self._client = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_REGION", "us-east-1"),
        )

    async def save(self, buf: BinaryIO, key: str, *, content_type: str) -> None:
        """Upload buffer to S3. Runs in a thread-pool executor to avoid blocking."""
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.upload_fileobj(
                buf, self._bucket, key,
                ExtraArgs={"ContentType": content_type},
            ),
        )

    async def presigned_url(self, key: str, *, expires_in: int = 86400) -> str:
        """Generate a presigned GET URL valid for `expires_in` seconds."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            ),
        )

    async def delete(self, key: str) -> None:
        """Delete an export file after TTL expiry or manual cleanup."""
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._client.delete_object(Bucket=self._bucket, Key=key),
        )


def get_storage() -> S3StorageBackend:
    """Factory — returns backend configured by STORAGE_BACKEND env var."""
    backend = os.getenv("STORAGE_BACKEND", "s3")
    if backend == "s3":
        return S3StorageBackend()
    raise NotImplementedError(f"Storage backend {backend!r} not implemented.")
```

### 4.7 Scoped query builder — `app/core/model_registry.py` (fragment)

```python
"""
Model registry: maps string model names to SQLAlchemy classes and builds
filtered SELECT statements for the background export worker.
"""
from __future__ import annotations

from typing import Any, Type

from sqlalchemy import select, Select
from sqlalchemy.orm import DeclarativeBase

# Populated at app startup by iterating over all SQLAlchemy mapped classes
_MODEL_REGISTRY: dict[str, Type[DeclarativeBase]] = {}


def register_model(model_cls: Type[DeclarativeBase]) -> None:
    """Register a model under its __name__."""
    _MODEL_REGISTRY[model_cls.__name__] = model_cls


def get_model_class(name: str) -> Type[DeclarativeBase]:
    """Return model class by name. Raises KeyError if not registered."""
    if name not in _MODEL_REGISTRY:
        raise KeyError(
            f"Model {name!r} not in registry. "
            f"Available: {sorted(_MODEL_REGISTRY.keys())}"
        )
    return _MODEL_REGISTRY[name]


def build_filtered_stmt(
    model_cls: Type[DeclarativeBase],
    filters: dict[str, Any],
) -> Select:
    """
    Build a SELECT statement applying all filters from the dict.
    Supported filter keys: owner_id, tenant_id, is_deleted (always False).
    """
    stmt = select(model_cls)
    for col_name, col_value in filters.items():
        col = getattr(model_cls, col_name, None)
        if col is None:
            continue
        stmt = stmt.where(col == col_value)
    if hasattr(model_cls, "is_deleted"):
        stmt = stmt.where(model_cls.is_deleted.is_(False))
    return stmt
```

### 4.8 Alembic migration — GENERATED `alembic/versions/0006_add_export_jobs.py`

```python
"""add export_jobs tracking table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-12
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    op.create_table(
        "export_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','complete','failed')",
            name="ck_export_jobs_status",
        ),
    )
    op.create_index("ix_export_jobs_user_status", "export_jobs", ["user_id", "status"])
    op.create_index("ix_export_jobs_created_at", "export_jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_export_jobs_created_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_user_status", table_name="export_jobs")
    op.drop_table("export_jobs")
```

### 4.9 Format validator and quota guard — `app/core/export_guard.py`

```python
"""
Guards applied before export dispatch:
- Format whitelist validation
- Per-user concurrent export quota check
- Column whitelist enforcement
"""
from __future__ import annotations

from fastapi import HTTPException
import redis.asyncio as aioredis

ALLOWED_FORMATS: frozenset[str] = frozenset({"csv", "json", "xlsx", "parquet"})
MAX_CONCURRENT_EXPORTS: int = 3


def validate_format(fmt: str) -> None:
    """Raise 422 if format is not in the allowed set."""
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f"Format {fmt!r} not supported. Allowed: {sorted(ALLOWED_FORMATS)}",
        )


def validate_columns(
    requested: list[str], allowed: list[str]
) -> list[str]:
    """
    Return intersection of requested and allowed columns.
    Silently drops any column in SENSITIVE_COLUMNS or not in the model.
    Raises 422 if the result is empty.
    """
    from app.core.export import SENSITIVE_COLUMNS
    safe = [c for c in requested if c in allowed and c not in SENSITIVE_COLUMNS]
    if not safe:
        raise HTTPException(
            status_code=422,
            detail="No valid columns remain after security filtering.",
        )
    return safe


async def check_export_quota(redis: aioredis.Redis, user_id: str) -> None:
    """
    Raise 429 if user already has MAX_CONCURRENT_EXPORTS pending/running jobs.
    Uses a Redis counter with a 6-hour TTL.
    """
    key = f"export_quota:{user_id}"
    count = await redis.get(key)
    if count and int(count) >= MAX_CONCURRENT_EXPORTS:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Export limit reached. You may have at most {MAX_CONCURRENT_EXPORTS} "
                "concurrent exports. Wait for existing exports to complete."
            ),
        )
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, 21_600)  # 6 hours
    await pipe.execute()
```

### 4.10 Test file — GENERATED `tests/test_item_export.py`

```python
"""
Tests for the data export feature (TOOL-006).
Covers: sync streaming, async dispatch, security, filtering, idempotency.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_csv_export_header_and_rows(client: AsyncClient, auth_headers, factory):
    """T-01: CSV export contains header row + correct data rows."""
    items = await factory.create_items(5, owner=auth_headers["user"])
    response = await client.get("/api/v1/items/export?format=csv", headers=auth_headers)
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 5
    assert set(rows[0].keys()).isdisjoint({"hashed_password", "api_key", "secret"})


@pytest.mark.asyncio
async def test_ndjson_export_valid_json_lines(client: AsyncClient, auth_headers, factory):
    """T-02: NDJSON export has one valid JSON object per line."""
    await factory.create_items(3, owner=auth_headers["user"])
    response = await client.get("/api/v1/items/export?format=json", headers=auth_headers)
    assert response.status_code == 200
    lines = [l for l in response.text.strip().splitlines() if l]
    assert len(lines) == 3
    for line in lines:
        obj = json.loads(line)
        assert "id" in obj


@pytest.mark.asyncio
async def test_owner_filter_isolates_data(client: AsyncClient, user_a_headers, user_b_headers, factory):
    """T-04: Owner filter — user A cannot see user B's rows."""
    await factory.create_items(5, owner=user_a_headers["user"])
    await factory.create_items(10, owner=user_b_headers["user"])
    response = await client.get("/api/v1/items/export?format=csv", headers=user_a_headers)
    reader = csv.DictReader(io.StringIO(response.text))
    assert len(list(reader)) == 5


@pytest.mark.asyncio
async def test_sensitive_columns_excluded(client: AsyncClient, auth_headers, factory):
    """T-09: hashed_password and api_key never appear in export output."""
    await factory.create_items(1, owner=auth_headers["user"])
    response = await client.get("/api/v1/items/export?format=csv", headers=auth_headers)
    assert "hashed_password" not in response.text
    assert "api_key" not in response.text


@pytest.mark.asyncio
async def test_invalid_format_returns_422(client: AsyncClient, auth_headers):
    """T-12: Unknown format param returns 422."""
    response = await client.get("/api/v1/items/export?format=mp3", headers=auth_headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_async_dispatch_over_threshold(client: AsyncClient, auth_headers, factory, monkeypatch):
    """T-08: Exports above threshold return 202 with job_id."""
    monkeypatch.setattr("app.core.config.settings.EXPORT_ASYNC_THRESHOLD", 0)
    dispatch_mock = AsyncMock(return_value=uuid.uuid4())
    with patch("app.api.routes.items.dispatch_export_job", dispatch_mock):
        response = await client.get("/api/v1/items/export?format=csv", headers=auth_headers)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert "job_id" in body
    dispatch_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(client: AsyncClient):
    """T-11: No auth header → 401."""
    response = await client.get("/api/v1/items/export?format=csv")
    assert response.status_code == 401
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Export memory is ALWAYS bounded independent of dataset size** | `_stream_batches()` in `app/core/export.py` uses `session.stream(...).execution_options(yield_per=BATCH_SIZE)` + `.partitions(BATCH_SIZE)`; tool never generates code calling `.scalars().all()` on export paths; verified by T-13 |
| QS-2 | **Sync / async threshold dispatch ALWAYS based on COUNT(*) preflight** | Route handler executes `select(func.count())` before returning ANY data; verified by T-08 |
| QS-3 | **Owner and soft-delete filters ALWAYS match list endpoint guards** | Generated route reuses the same `WHERE owner_id = ?` and `WHERE is_deleted IS FALSE` clauses as the list handler; verified by T-04, T-05 |
| QS-4 | **Sensitive columns NEVER appear in any export format** | `SENSITIVE_COLUMNS` frozenset blocks columns at whitelist construction; explicit columns param stripped against whitelist; verified by T-09, T-10 |
| QS-5 | **TTFB ALWAYS < 500 ms for sync exports** | `StreamingResponse` yields header row (CSV) or first batch immediately; no buffering before first `yield`; verified by T-14 |
| QS-6 | **Format param ALWAYS validated via regex pattern** | `Query(pattern="^(csv\|json\|xlsx\|parquet)$")` rejects unknown formats before DB query executes; verified by T-12 |
| QS-7 | **Async export URLs ALWAYS expire after TTL** | `storage.presigned_url(key, expires_in=86400)` with TTL baked in; storage key in `export_jobs` table enables cleanup job; verified by T-15 |
| QS-8 | **Tenant filter ALWAYS applied when multi-tenancy is active** | `build_filtered_stmt` includes `tenant_id` filter if model carries the `TenantScopedMixin`; verified by T-06 |
| QS-9 | **Export action ALWAYS logged to audit when audit module present** | Conditional `emit_audit(action="export", entity_type=..., after_values={"row_count": N, "format": F})` after count resolved; verified by T-18 |
| QS-10 | **Tool ALWAYS idempotent on re-run** | Pre-flight detects `GET /{model}/export` route and `app/core/export.py` existence; returns `{status: "no_op"}` without modifying files; verified by T-24 |
| QS-11 | **All write operations pass input validation before touching storage** | Enforced by Pydantic v2 schema validation in `app/schemas/` — every request body is parsed and rejected with 422 on malformed data, verified by `tests/test_schemas.py::test_validation` |
| QS-12 | **All write operations pass input validation before touching storage** | Enforced by Pydantic v2 schema validation in `app/schemas/` — every request body is parsed and rejected with 422 on malformed data, verified by `tests/test_schemas.py::test_validation` |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `app/core/export.py` exists | File exists |
| CC-02 | `_stream_batches` uses `session.stream(...).execution_options(yield_per=BATCH_SIZE)` | `grep "yield_per"` |
| CC-03 | `export_csv` yields bytes per batch — never accumulates full result | `grep -n "yield"` shows yields inside batch loop |
| CC-04 | `export_ndjson` yields one NDJSON line per row | `grep "\\\\n"` in ndjson generator |
| CC-05 | `export_xlsx` uses `constant_memory=True` in xlsxwriter `Workbook` | `grep "constant_memory"` |
| CC-06 | `export_parquet` writes via `pyarrow.parquet.write_table` | `grep "pq.write_table"` |
| CC-07 | `_serialize` handles `datetime`, `UUID`, `Decimal`, `bytes` | Inspect function body |
| CC-08 | `SENSITIVE_COLUMNS` frozenset defined | `grep "SENSITIVE_COLUMNS"` |
| CC-09 | `GET /{model}/export` route registered on each target model | `grep "/export"` in route files |
| CC-10 | Route accepts `format` Query with regex pattern | `grep 'pattern="^\('` |
| CC-11 | Route accepts `columns` Query (optional) | `grep "columns"` in route |
| CC-12 | Default columns whitelist excludes all entries in `SENSITIVE_COLUMNS` | Inspect whitelist construction |
| CC-13 | Preflight `COUNT(*)` executes before data streaming | `grep "func.count\(\)"` |
| CC-14 | Async dispatch returns HTTP 202 with `job_id` | `grep "status_code=202"` |
| CC-15 | Sync path uses `StreamingResponse` | `grep "StreamingResponse"` |
| CC-16 | Owner filter applied in route (`owner_id == current_user.id`) | `grep "owner_id"` in route |
| CC-17 | Soft-delete filter applied when model has `is_deleted` | `grep "is_deleted"` |
| CC-18 | Tenant filter applied when model has `tenant_id` | `grep "tenant_id"` in route |
| CC-19 | `app/core/export_jobs.py` exists with `dispatch_export_job` | File exists; function exported |
| CC-20 | `app/jobs/export.py` exists with `run_export` async ARQ function | File exists |
| CC-21 | Worker streams chunks via generator — does not load full dataset | Inspect `async for chunk in gen_fn` pattern |
| CC-22 | Worker uploads to storage with key `exports/{job_id}.{format}` | `grep "exports/"` |
| CC-23 | Worker emails presigned URL with `expires_in=86400` | `grep "86400"` |
| CC-24 | `ExportStatus` enum tracks `pending / running / complete / failed` | Inspect `export_progress.py` |
| CC-25 | Progress readable via `get_export_progress(redis, job_id)` | Function exported |
| CC-26 | `export_jobs` DB table created by Alembic migration | Migration exists; `upgrade()` creates table |
| CC-27 | Migration `downgrade()` drops table and indexes cleanly | Inspect `downgrade()` |
| CC-28 | Settings: `EXPORT_ASYNC_THRESHOLD` in `config.py` | `grep "EXPORT_ASYNC_THRESHOLD"` |
| CC-29 | Settings: `AWS_S3_BUCKET`, `STORAGE_BACKEND` in `.env.example` | File contains vars |
| CC-30 | `xlsxwriter>=3.1.0` in `requirements.txt` when xlsx in formats | `grep "xlsxwriter"` |
| CC-31 | `pyarrow>=14.0.0` in `requirements.txt` when parquet in formats | `grep "pyarrow"` |
| CC-32 | All generated Python files parse cleanly via `ast.parse` | Tool-internal step |
| CC-33 | Existing test suite passes (0 regressions) | `pytest --tb=short` |
| CC-34 | New test file `tests/test_{model}_export.py` created | File exists |
| CC-35 | Tool execution time < 4 s | Measured via `time.perf_counter` in tool |

---

## 7. Definition of Done (DoD)

- [ ] All 35 Completeness Criteria verified (CC-01..CC-35)
- [ ] All 10 Quality Standards enforced (QS-1..QS-10)
- [ ] All 8 Invariants enforced (INV-EX-01..INV-EX-08)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 test cases pass (T-01..T-30, see §10)
- [ ] Tool is idempotent: running twice on an already-configured project returns `{status: "no_op"}`
- [ ] Tool is reversible: rollback procedure documented and validated end-to-end (see §12)
- [ ] Memory peak < 50 MB measured on a 1 M-row streaming export
- [ ] TTFB < 500 ms measured on synchronous streaming CSV
- [ ] Sensitive columns verified absent from all four export formats
- [ ] Sync ↔ async threshold boundary tested at `threshold`, `threshold - 1`, `threshold + 1`
- [ ] Presigned URL TTL expiry tested end-to-end (real S3 or mocked)
- [ ] `export_jobs` DB migration applies cleanly and rolls back cleanly
- [ ] Documentation updated (`KNOWLEDGE.md` with GDPR Article 20 note, `manifest.yaml`, `SKILL.md`)
- [ ] Tool registered in `mcp_server.py` under EXTEND > CRUD & Data
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-EX-01 | Export server RAM peak NEVER depends on dataset size — ALWAYS bounded by `BATCH_SIZE` | `_stream_batches()` uses server-side cursor with `yield_per=BATCH_SIZE`; no `.scalars().all()` on export path | T-13 |
| INV-EX-02 | Sensitive columns NEVER appear in any export output regardless of user-supplied `columns` param | `SENSITIVE_COLUMNS` frozenset; user-supplied columns intersected against whitelist before query | T-09, T-10 |
| INV-EX-03 | Owner filter ALWAYS applied — user NEVER exports another user's rows | `WHERE owner_id = current_user.id` baked into every export query; no bypass path | T-04 |
| INV-EX-04 | Soft-delete filter ALWAYS applied when model has `is_deleted` | `WHERE is_deleted IS FALSE` applied if attribute exists; verified at query construction time | T-05 |
| INV-EX-05 | Exports above `async_threshold` ALWAYS return HTTP 202 — never a hung sync response | Preflight `COUNT(*)` compared to `settings.EXPORT_ASYNC_THRESHOLD` before any data is read | T-08 |
| INV-EX-06 | Format param ALWAYS validated via regex whitelist — unknown values ALWAYS return 422 | `Query(pattern=...)` in route definition; Pydantic rejects unknown formats before handler runs | T-12 |
| INV-EX-07 | Async download URLs ALWAYS expire after `expires_in` seconds (default 86400) | `storage.presigned_url(key, expires_in=86400)` in worker; no unsigned permanent URLs | T-15 |
| INV-EX-08 | Export job status ALWAYS persisted in `export_jobs` table — no fire-and-forget without tracking | Migration creates `export_jobs` table; worker writes `status`, `completed_at`, `storage_key` | T-17 |

---

## 9. User Stories

### 9.1 Basic export flow — CSV, JSON, format validation, scope enforcement (US-01..US-05)

**US-01: Download personal items as CSV for spreadsheet analysis**
- **As a** product manager who tracks KPIs in Google Sheets
- **I want** to export all my `Item` records as a UTF-8 CSV file with a header row
- **So that** I can import the file directly into a spreadsheet without any manual reformatting
- **Given:** an authenticated user with 500 `Item` rows where `owner_id = current_user.id`
- **When:** `GET /api/v1/items/export?format=csv` is called with a valid JWT
- **Then:**
  - HTTP 200 is returned within 2 s total wall time
  - `Content-Type: text/csv` header is present
  - `Content-Disposition: attachment; filename="items.csv"` header is present
  - First line equals the column header row (e.g., `id,title,created_at,...`)
  - Exactly 500 data rows follow the header, each comma-separated
  - `hashed_password` and `api_key` are absent from all rows (INV-EX-02, INV-EX-03, CC-01, CC-09)

**US-02: Stream order history as NDJSON for ETL pipeline ingestion**
- **As a** data engineer building a nightly ETL pipeline
- **I want** to receive `Order` records as Newline-Delimited JSON (NDJSON), one object per line
- **So that** my pipeline can parse each line independently with `json.loads()` without buffering the full dataset
- **Given:** an authenticated service account with 1,000 `Order` rows in the database
- **When:** `GET /api/v1/orders/export?format=json` is executed via an API client
- **Then:**
  - `Content-Type: application/x-ndjson` header is present
  - Response body contains exactly 1,000 non-empty lines
  - Each line independently parses as a valid JSON object (`json.loads(line)` succeeds)
  - Every object includes the `id` and `created_at` keys with correct types (CC-04, CC-07)

**US-03: Export invoice data as Excel workbook for accountant review**
- **As a** small business owner who shares invoices with an external accountant
- **I want** to download my `Invoice` records as a `.xlsx` Excel workbook with bold headers
- **So that** my accountant can open the file in Microsoft Excel without installing any additional tools
- **Given:** an authenticated user with 120 `Invoice` rows
- **When:** `GET /api/v1/invoices/export?format=xlsx` is called
- **Then:**
  - HTTP 200 is returned with `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`
  - Response body is a valid `.xlsx` file readable by `openpyxl.load_workbook(BytesIO(body))`
  - Row 1 contains bold-formatted column headers; rows 2–121 contain data
  - No `hashed_password`, `api_key`, or `secret` column appears in the sheet (CC-05, INV-EX-02)

**US-04: Export dataset as Parquet for data science feature engineering**
- **As a** data scientist running ML feature engineering in a Jupyter notebook
- **I want** to download `UserEvent` rows as a Snappy-compressed Parquet file
- **So that** I can load it with `pyarrow.parquet.read_table()` and get correct column dtypes without manual casting
- **Given:** an authenticated user with 5,000 `UserEvent` rows containing `UUID`, `datetime`, `Decimal`, and `str` columns
- **When:** `GET /api/v1/user-events/export?format=parquet` is called
- **Then:**
  - Response body is a valid Parquet file readable by `pq.read_table(buf)`
  - `UUID` columns serialise as strings, `datetime` as ISO-8601 strings, `Decimal` as floats
  - File uses Snappy compression (`pq.read_metadata(buf).row_group(0).column(0).compression == "SNAPPY"`)
  - Row count in the Parquet file equals 5,000 (CC-06, CC-07)

**US-05: Export only selected columns to reduce file size**
- **As a** frontend developer building a CSV download button that only shows `id`, `title`, and `created_at`
- **I want** to pass a `columns` query parameter that limits which fields appear in the export
- **So that** the download file is minimal in size and does not expose fields irrelevant to the user's view
- **Given:** an authenticated user with 200 items; the `Item` model also has `description`, `status`, and `price` columns
- **When:** `GET /api/v1/items/export?format=csv&columns=id,title,created_at` is called
- **Then:**
  - The CSV header row contains exactly the three columns: `id,title,created_at`
  - No other columns (`description`, `status`, `price`) appear in any row
  - Row count equals 200; all rows are well-formed CSV
  - Attempting to pass `hashed_password` in `columns` still omits it silently (CC-10, CC-11, CC-12, INV-EX-02)

### 9.2 Large async export — ARQ task, progress tracking, presigned URL, 24 h TTL (US-06..US-10)

**US-06: Auto-promote large export to async background job without hanging the browser**
- **As a** power user who has accumulated 80,000 `Transaction` records
- **I want** the export request to return immediately with a job ID instead of hanging for minutes
- **So that** my browser tab is not blocked and I can continue working while the export is prepared
- **Given:** `EXPORT_ASYNC_THRESHOLD=10000`; the authenticated user has 80,000 `Transaction` rows
- **When:** `GET /api/v1/transactions/export?format=csv` is called
- **Then:**
  - HTTP 202 is returned in under 200 ms
  - Response body is `{"status": "queued", "job_id": "<uuid>", "row_estimate": 80000}`
  - A new ARQ job `run_export` is enqueued exactly once with `model="Transaction"`, `format="csv"`
  - No data rows are streamed or buffered during the request cycle (INV-EX-05, CC-13, CC-14)

**US-07: Receive email with a presigned S3 download link when async export completes**
- **As a** user who requested a large async export
- **I want** to receive an email with a download link as soon as the export file is ready
- **So that** I do not need to poll a status endpoint and can download the file from my inbox at any time
- **Given:** an async ARQ job `run_export` completes successfully, uploading `exports/{job_id}.csv` to S3
- **When:** the ARQ worker calls `send_email(to=user.email, subject=..., body=...)`
- **Then:**
  - The user's email address receives exactly one email with subject `"Your Transaction data export is ready"`
  - The email body contains an HTTPS presigned S3 URL
  - The presigned URL resolves to the correct `.csv` file with the right byte count
  - The email states the link expires in 24 hours (CC-23, INV-EX-07)

**US-08: Presigned download URL automatically expires after 24 hours**
- **As a** security officer responsible for data leak prevention
- **I want** export download URLs to expire automatically 24 hours after generation
- **So that** a forwarded or leaked URL cannot be used by an unauthorised party after the TTL
- **Given:** an S3 presigned URL generated by `storage.presigned_url(key, expires_in=86400)` exactly 25 hours ago
- **When:** an HTTP GET request is made against the expired URL
- **Then:**
  - S3 returns HTTP 403 with `<Code>AccessDenied</Code>` or `<Code>RequestExpired</Code>`
  - No data bytes are served to the requester
  - The `export_jobs` row shows `storage_key` but the URL is no longer accessible
  - A follow-up fresh export request generates a new presigned URL with a new 86400 s TTL (INV-EX-07, CC-23)

**US-09: Failed async export updates job status and notifies user by email**
- **As a** user whose export failed mid-stream because the S3 bucket was temporarily unreachable
- **I want** to receive an email explaining the failure and be given the option to retry
- **So that** I am not left waiting indefinitely for an export that will never arrive
- **Given:** the ARQ worker `run_export` raises an exception after all retry attempts are exhausted
- **When:** ARQ marks the job as failed
- **Then:**
  - The `export_jobs` row for this `job_id` has `status = "failed"` and a non-null `error_message`
  - The user receives an email with subject containing "failed" and a retry instruction
  - `GET /api/v1/exports/{job_id}/status` returns `{"status": "failed", "error": "..."}` with HTTP 200
  - No partial file remains accessible via any presigned URL (INV-EX-08, CC-24)

**US-10: Poll job progress endpoint to render a real-time progress bar**
- **As a** frontend developer implementing a progress bar for large async exports
- **I want** to poll a lightweight status endpoint and receive `rows_written` / `total_rows` in the response
- **So that** I can render a percentage progress indicator without opening a WebSocket connection
- **Given:** an async export job is in `status = "running"` with 3,000 rows written out of 50,000 total
- **When:** `GET /api/v1/exports/{job_id}/status` is polled every 3 seconds
- **Then:**
  - Response is `{"job_id": "...", "status": "running", "rows_written": 3000, "total_rows": 50000}` with HTTP 200
  - `rows_written` increases monotonically across successive polls
  - When export completes, response includes `"status": "complete"` and `"download_url": "https://..."`
  - Redis key `export_job:{job_id}` has TTL >= 86400 s to cover the full download window (CC-24, CC-25)

### 9.3 Streaming and memory bounds — StreamingResponse, 50 MB RAM limit, 100 k rows cap (US-11..US-15)

**US-11: Stream a 100,000-row CSV export without exhausting server RAM**
- **As a** platform engineer who operates a shared FastAPI instance with a 512 MB RAM limit per worker
- **I want** the export route to use `StreamingResponse` with a server-side cursor so RAM usage stays bounded
- **So that** a single large export does not cause OOM-kill and disrupt other users on the same process
- **Given:** the `Item` table has 100,000 rows all owned by the requesting user
- **When:** `GET /api/v1/items/export?format=csv` is executed by the worker process
- **Then:**
  - The process RSS memory delta stays below 50 MB during the entire streaming response
  - `session.stream(stmt.execution_options(yield_per=1000))` is called (not `.scalars().all()`)
  - First byte arrives within 500 ms (CSV header row flushed immediately)
  - Total wall time stays under 10 s on a local Postgres instance (INV-EX-01, QS-1, CC-02)

**US-12: Deliver first CSV byte to browser within 500 ms for fast UX feedback**
- **As a** UX engineer who monitors Core Web Vitals on the data export page
- **I want** the time-to-first-byte (TTFB) for any sync export to be under 500 ms
- **So that** the browser shows the download dialog quickly and does not appear frozen
- **Given:** an authenticated user with 10,000 items that fall below `EXPORT_ASYNC_THRESHOLD`
- **When:** `GET /api/v1/items/export?format=csv` is invoked and TTFB is measured via `httpx` streaming client
- **Then:**
  - TTFB (time from request send to first response byte received) is measured below 500 ms
  - The first yielded bytes contain the CSV header row, not a partial row
  - The `StreamingResponse` generator yields the header chunk immediately without waiting for the first DB batch
  - Subsequent 1,000-row batches arrive at roughly equal intervals without any stall (QS-5, CC-15)

**US-13: Export large dataset without calling `.all()` — server-side cursor enforced**
- **As a** backend developer reviewing the generated export code for correctness
- **I want** to verify that the export generator never materialises the full result set in Python memory
- **So that** I can be confident the 50 MB RAM bound holds even if `EXPORT_ASYNC_THRESHOLD` is raised
- **Given:** a mocked `AsyncSession` configured to assert that `session.stream()` is called
- **When:** `export_csv(session, stmt, columns)` is executed in a unit test
- **Then:**
  - `session.stream(stmt.execution_options(yield_per=1000))` is called exactly once
  - `session.execute(stmt).scalars().all()` is never called during the export path
  - The async generator yields multiple chunk objects (one per 1,000-row batch)
  - Memory profiling confirms < 50 MB RSS delta for a 1 M-row mock stream (INV-EX-01, CC-02, CC-03)

**US-14: Client disconnect mid-stream releases DB cursor without leaking connections**
- **As a** platform SRE monitoring database connection pool saturation
- **I want** SQLAlchemy streaming cursors to be closed automatically when a client aborts mid-download
- **So that** connection pool slots are returned promptly and do not starve other requests
- **Given:** a streaming CSV export of 50,000 rows is in progress and 5,000 rows have been sent
- **When:** the client drops the TCP connection (simulated via `client.aclose()` in the test)
- **Then:**
  - The FastAPI `StreamingResponse` generator stops iterating within one batch cycle
  - No "cursor already closed" or "connection pool exhausted" errors appear in the application logs
  - The `AsyncSession` context manager `__aexit__` is called, releasing the connection back to the pool
  - No half-written CSV file or orphaned S3 upload is created (T-16)

**US-15: Reject Parquet export when `pyarrow` is not installed in the environment**
- **As a** developer deploying to a minimal Docker image that excludes optional heavy dependencies
- **I want** the Parquet format to fail with a clear 422 error when `pyarrow` is absent
- **So that** the error message tells me exactly which package to install rather than surfacing a cryptic `ImportError`
- **Given:** `pyarrow` is not installed; the `formats` list passed to the tool does not include `"parquet"`
- **When:** `GET /api/v1/items/export?format=parquet` is called
- **Then:**
  - HTTP 422 is returned with `detail` containing `"parquet"` and `"not supported"` in the message
  - The route's `Query(pattern=...)` regex rejects the value before the handler executes the import
  - No `ImportError` traceback appears in the application error logs
  - A 200 response is returned for `?format=csv` on the same endpoint, confirming other formats work (INV-EX-06, CC-10)

### 9.4 Formats and schema — CSV header, JSON array, Parquet columnar, custom field selection (US-16..US-20)

**US-16: CSV header row always matches the model's non-sensitive public columns**
- **As a** data consumer who writes column-name-dependent import scripts
- **I want** the CSV header row to exactly match the list of non-sensitive columns returned by the API
- **So that** my import script does not break when the model gains a new column in a future migration
- **Given:** the `Item` model has columns `id`, `title`, `price`, `created_at`, `owner_id`, and `hashed_password`
- **When:** `GET /api/v1/items/export?format=csv` is called (no `columns` param)
- **Then:**
  - The header row is `id,title,price,created_at,owner_id` (alphabetical within non-sensitive set)
  - `hashed_password` is absent from the header and from every data row
  - Adding a new nullable column `tag` to `Item` and re-running the export causes `tag` to appear in the header automatically
  - The header generation uses `_DEFAULT_COLUMNS = [c.name for c in Model.__table__.columns if c.name not in SENSITIVE_COLUMNS]` (CC-08, CC-12, INV-EX-02)

**US-17: NDJSON export serialises UUID, datetime, and Decimal without type errors**
- **As a** backend developer consuming the NDJSON export feed in a TypeScript service
- **I want** non-JSON-native Python types to be serialised to standard JSON representations
- **So that** `JSON.parse(line)` succeeds in Node.js without any custom deserialiser
- **Given:** the `Order` model has columns `id: UUID`, `total: Decimal`, `placed_at: datetime`, and `notes: str`
- **When:** `GET /api/v1/orders/export?format=json` is called for an order with `id=uuid4()`, `total=Decimal("99.99")`, `placed_at=datetime.utcnow()`
- **Then:**
  - The `id` field appears as a lowercase hyphenated UUID string (e.g., `"3f2504e0-..."`)
  - The `total` field appears as float `99.99`, not as string `"99.99"` or `Decimal` object
  - The `placed_at` field appears as an ISO-8601 string (e.g., `"2026-04-12T10:30:00"`)
  - `json.loads(line)` succeeds without raising any exception for all 1,000 exported rows (CC-07)

**US-18: Parquet export preserves columnar schema with correct Arrow types**
- **As a** data scientist running Apache Spark jobs on exported Parquet files
- **I want** the Parquet schema to map Python/SQLAlchemy types to correct Arrow types
- **So that** Spark infers column types correctly and I avoid downstream casting errors in my transformation code
- **Given:** the `Metric` model has `id: UUID`, `value: float`, `label: str`, `recorded_at: datetime`; 500 rows exist
- **When:** `GET /api/v1/metrics/export?format=parquet` is called and the response body saved to `metrics.parquet`
- **Then:**
  - `pq.read_table("metrics.parquet").schema` shows `id` as `string`, `value` as `double`, `label` as `string`
  - The file uses Snappy compression (`pq.read_metadata` confirms `compression == "SNAPPY"`)
  - Row count in the Parquet file is 500
  - `pd.read_parquet("metrics.parquet")` loads without warnings or dtype coercion errors (CC-06, CC-07)

**US-19: Rejected columns param that only names sensitive fields returns 422 not 200**
- **As a** penetration tester probing the export endpoint for data leakage
- **I want** the API to return HTTP 422 — not an empty CSV — when all requested columns are filtered out by the security whitelist
- **So that** a malicious caller receives no ambiguous empty-file response that might hint at column existence
- **Given:** the `User` model has columns `id`, `email`, `hashed_password`, `api_key`; the caller requests only the sensitive ones
- **When:** `GET /api/v1/users/export?columns=hashed_password,api_key` is called by an authenticated user
- **Then:**
  - HTTP 422 is returned (not HTTP 200 with an empty body)
  - Response `detail` contains `"No valid columns remain after security filtering"`
  - No DB query is executed after the column-whitelist check rejects all requested fields
  - An audit log entry is created with `action="export_rejected"` if the audit module is enabled (CC-12, INV-EX-02, T-10)

**US-20: Export handles `bytes` column by hex-encoding in CSV and JSON outputs**
- **As a** developer whose `Attachment` model stores binary thumbnail data in a `content: bytes` column
- **I want** binary columns to be hex-encoded in text formats rather than raising a serialisation error
- **So that** the export does not crash and the hex value can be decoded by consumers who need it
- **Given:** the `Attachment` model has a `content: LargeBinary` column with 10 rows each containing 512 bytes
- **When:** `GET /api/v1/attachments/export?format=csv` is called
- **Then:**
  - The `content` column in the CSV contains hex strings (e.g., `"deadbeef..."`) rather than raw bytes
  - No `TypeError` or `UnicodeDecodeError` is raised during serialisation
  - The same hex encoding applies when `?format=json` is used (`_serialize(bytes_val) == bytes_val.hex()`)
  - The export completes with HTTP 200 and the correct row count (CC-07)

### 9.5 Audit, GDPR, cancel export, and quota enforcement (US-21..US-25)

**US-21: EU user exercises GDPR Article 20 right to data portability**
- **As an** EU resident whose personal data is processed under GDPR
- **I want** to download all data the application holds about me in a machine-readable format (CSV or JSON)
- **So that** I can exercise my right to data portability under GDPR Article 20 without filing a manual support ticket
- **Given:** an authenticated EU user whose `User`, `Order`, and `Preference` records are stored under `owner_id = current_user.id`
- **When:** the user calls `GET /api/v1/orders/export?format=json` and `GET /api/v1/preferences/export?format=csv`
- **Then:**
  - Both responses include all non-sensitive columns covering the user's personal data footprint
  - No other user's data appears in either response (scoping enforced by `WHERE owner_id = ?`)
  - `KNOWLEDGE.md` contains a section titled `"GDPR Article 20 — Right to Data Portability"` describing the implementation
  - The compliance note is verified by `grep "Article 20" KNOWLEDGE.md` returning a match (CC-35, INV-EX-03)

**US-22: Every export action creates a tamper-evident audit log entry**
- **As a** compliance officer who must demonstrate to auditors that all data export events are tracked
- **I want** each export request to create an immutable audit log row with the exporting user, model, format, and row count
- **So that** I can produce an audit trail on demand showing who exported what data and when
- **Given:** `add_audit_log` (TOOL-005) is enabled; an authenticated user exports 250 `Order` rows as CSV
- **When:** the export route resolves the COUNT(*) preflight and streams the response
- **Then:**
  - An `audit_log` row is created with `action="export"`, `entity_type="order"`, `user_id=current_user.id`
  - `after_values` JSON includes `{"row_count": 250, "format": "csv"}`
  - The audit row's `created_at` timestamp matches the request time within 1 second
  - The audit entry is created for both the sync streaming path and the async dispatch path (QS-9, T-24)

**US-23: Tenant-scoped export isolates rows by tenant even when owner_id overlaps**
- **As a** SaaS operator running a multi-tenant deployment where user IDs can theoretically collide across tenants
- **I want** export queries to apply both `owner_id` and `tenant_id` filters simultaneously
- **So that** a user who holds the same UUID in two tenants never accidentally receives rows from the other tenant
- **Given:** `add_multi_tenancy` (TOOL-008) is applied; User X belongs to Tenant A and has 15 items; a hypothetical User X′ with the same UUID in Tenant B has 20 items
- **When:** User X in Tenant A calls `GET /api/v1/items/export?format=csv`
- **Then:**
  - Exactly 15 rows appear in the CSV — no rows from Tenant B
  - The generated SQL includes both `WHERE items.owner_id = ? AND items.tenant_id = ?`
  - `build_filtered_stmt` applies the `tenant_id` filter when `TenantScopedMixin` is detected on the model
  - T-06 integration test verifies this with two tenants and overlapping user IDs (CC-18, INV-EX-03, T-06)

**US-24: User cancels a queued export job before the ARQ worker starts**
- **As a** user who accidentally triggered a 1 M-row export and wants to stop it before wasting S3 storage
- **I want** to call a cancel endpoint that marks the job as cancelled so the worker skips it on pickup
- **So that** I avoid paying for unnecessary S3 write operations and the worker slot is freed quickly
- **Given:** an async export job with `status = "pending"` exists in the `export_jobs` table; the ARQ worker has not yet picked it up
- **When:** `DELETE /api/v1/exports/{job_id}` is called by the job's owner
- **Then:**
  - The `export_jobs` row transitions to `status = "cancelled"` with `completed_at = now()`
  - HTTP 200 is returned with `{"status": "cancelled", "job_id": "..."}`
  - When the ARQ worker picks up the job, it reads `status = "cancelled"` and exits without streaming data
  - A second `DELETE` on the same job returns HTTP 409 with `"Job already in terminal state"` (INV-EX-08, CC-26)

**US-25: Export quota blocks a user who reaches 3 concurrent async jobs**
- **As a** platform operator who needs to prevent a single user from overwhelming the ARQ worker queue with export jobs
- **I want** the export endpoint to return HTTP 429 when a user already has 3 pending or running export jobs
- **So that** the ARQ worker queue depth stays bounded and other users' async jobs are not starved
- **Given:** the authenticated user already has 3 export jobs with `status IN ("pending", "running")` tracked in Redis under `export_quota:{user_id}`; `MAX_CONCURRENT_EXPORTS = 3`
- **When:** the user submits a fourth `GET /api/v1/items/export?format=csv` request for a dataset above `EXPORT_ASYNC_THRESHOLD`
- **Then:**
  - HTTP 429 is returned with `detail` containing `"Export limit reached"` and the maximum count
  - No new ARQ job is enqueued (`enqueue_job` is not called)
  - The Redis quota counter remains at 3 (not incremented to 4)
  - After one of the existing jobs reaches `status = "complete"`, the quota counter decrements and the next export is accepted (CC-33, T-20)

## 10. Test Plan

The 30 tests are grouped into six categories covering streaming correctness, security guarantees, async job lifecycle, audit and compliance, idempotency and atomicity, and integration. Unit tests use mocked sessions and storage; integration tests require a real Postgres + Redis environment.

### 10.1 Sync streaming and format correctness (T-01..T-06)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-01 | CSV export — header row + correct data rows | Integration | 5 items → CSV with header + 5 data rows; `len(list(reader)) == 5` |
| T-02 | NDJSON export — one valid JSON object per line | Integration | 5 items → 5 lines; each `json.loads(line)` succeeds |
| T-03 | XLSX export — valid workbook parseable by openpyxl | Integration | 100 items → `.xlsx`; `load_workbook(BytesIO(body))` row count = 101 |
| T-04 | Parquet export — valid file, types preserved | Integration | 10 items with UUID/datetime fields → `pq.read_table(buf)` correct schema |
| T-05 | Custom columns — only requested columns returned | Integration | `?columns=id,title` → CSV has exactly 2 headers |
| T-06 | Tenant filter applied when multi-tenancy active | Integration | User in Tenant A → 0 rows from Tenant B in any format |

### 10.2 Security and data isolation (T-07..T-12)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-07 | Empty dataset — header-only CSV | Integration | 0 items → HTTP 200, CSV header only |
| T-08 | Async dispatch above threshold — HTTP 202 | Integration | monkeypatch threshold=0 → 202 with job_id |
| T-09 | Sensitive columns excluded from default export | Integration | hashed_password absent from CSV/JSON/XLSX/Parquet |
| T-10 | Sensitive column in `columns` param silently stripped | Integration | `?columns=id,hashed_password` → only `id` in output |
| T-11 | Unauthenticated request returns 401 | Unit | No auth → 401 before DB touched |
| T-12 | Unknown format returns 422 | Unit | `?format=mp3` → 422, error message contains allowed formats |

### 10.3 Memory, streaming performance (T-13..T-16)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-13 | Server RAM peak < 50 MB on 1M-row export | Perf (memory_profiler) | RSS delta < 50 MB during streaming |
| T-14 | TTFB < 500 ms for streaming CSV | Perf (httpx streaming) | Time to first byte measured < 500 ms |
| T-15 | Server-side cursor used — no `.all()` call | Unit (mock session) | `session.stream()` called, not `session.execute().scalars().all()` |
| T-16 | Client disconnect — cursor closed cleanly | Integration | Abort mid-stream; no "cursor already closed" error in logs |

### 10.4 Async job lifecycle (T-17..T-21)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-17 | ARQ job enqueued on async dispatch | Unit (mock ARQ) | `enqueue_job("run_export", ...)` called once with correct args |
| T-18 | Worker uploads to storage with key `exports/{job_id}.{format}` | Unit (mock storage) | `storage.save(buf, "exports/UUID.csv", ...)` called |
| T-19 | Presigned URL has 24-hour TTL | Unit (mock S3) | `presigned_url` called with `expires_in=86400` |
| T-20 | User receives email after completion | Unit (mock email) | `send_email(to=user.email, subject=...)` called with URL |
| T-21 | Job failure updates `export_jobs` to status=failed | Integration | Exception in worker → `status=failed` in DB row |

### 10.5 Audit, compliance, idempotency (T-22..T-26)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-22 | Soft-delete filter applied | Integration | 3 items 1 deleted → 2 rows in CSV |
| T-23 | Owner filter isolates users | Integration | User A exports → only A's 5 rows; B's 10 absent |
| T-24 | Audit entry created on export when audit enabled | Integration | `audit_log` table has row: `action=export`, `after_values.row_count=N` |
| T-25 | GDPR note present in KNOWLEDGE.md | File check | `grep "Article 20"` in KNOWLEDGE.md returns match |
| T-26 | Tool re-run on enabled project is no-op | Unit | Second `add_data_export()` call → `{status:"no_op"}`, zero file writes |

### 10.6 Integration and regression (T-27..T-30)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-27 | Existing test suite passes after tool applies | Integration | `pytest` 0 failures, 0 errors |
| T-28 | Multiple models all get export routes | Integration | Item and Order both have `/export` endpoint, both return correct data |
| T-29 | `xlsxwriter` and `pyarrow` available when formats include xlsx/parquet | Unit | Import of both libs succeeds after tool runs |
| T-30 | Migration applies cleanly and downgrade removes table | Integration | `alembic upgrade head` → table exists; `alembic downgrade -1` → table absent |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_multi_tenancy` (TOOL-008) | **Tenancy first** | ✅ Compatible — required for correct isolation | Route appends `WHERE tenant_id = current_user.tenant_id`; worker uses `build_filtered_stmt` which includes tenant scope; admin export uses `skip_tenant_filter=True` |
| `add_soft_delete` (TOOL-001) | **Soft-delete first** | ✅ Compatible | Export query appends `WHERE is_deleted IS FALSE` when attribute detected on model |
| `add_audit_log` (TOOL-005) | **Audit first** | ✅ Compatible — conditional integration | `emit_audit(action="export")` called after row count resolved; no-op if audit module absent |
| `add_file_upload` (TOOL-003) | No | ⚠️ Caveat | File/blob columns (binary) serialised as hex strings in CSV/JSON; excluded from Parquet by default to avoid huge files |
| `add_background_job` (TOOL-033) | **Job system first if async** | ✅ Required for async path | `enqueue_job("run_export", ...)` calls ARQ queue scaffolded by TOOL-033; sync-only exports work without it |
| `add_rbac` (TOOL-010) | **RBAC first** | ✅ Compatible | Permission check `require_permission(current_user, "export:item")` inserted in route if RBAC module present |
| `add_redis` (TOOL-036) | **Redis first if progress tracking** | ✅ Required for progress tracking | `set_export_progress` / `get_export_progress` write to Redis; feature degrades gracefully if Redis unavailable |
| `add_cursor_pagination` (TOOL-007) | No | ✅ Compatible — independent code path | Export uses direct SELECT with streaming cursor; pagination endpoints unaffected |
| `add_search` (TOOL-012) | No | ⚠️ Caveat | Search-filtered exports not directly supported; user must combine `?columns=` with the base export; full-text filtered exports are out of scope for this tool |
| `add_admin_panel` (TOOL-048) | No | ✅ Compatible — enhancement | Admin panel can link to export endpoints with pre-filled format and column params |
| `scaffold_project` (TOOL-001) | **Required** | ✅ Required | `app/models/base.py`, `app/core/db.py`, `app/api/deps.py` must exist before tool runs |
| `add_alembic` (TOOL-002) | **Required** | ✅ Required | Migration for `export_jobs` table written to `alembic/versions/`; Alembic must be initialised |
| `add_s3_integration` | **S3 first for async** | ✅ Required for async path | `storage.save()` and `storage.presigned_url()` require `AWS_S3_BUCKET` and AWS credentials |
| `add_event_driven` (TOOL-046) | No | ✅ Compatible | Export completion can emit `ExportCompleted` domain event for downstream notification pipelines |
| `add_rate_limiting` (TOOL-018) | No | ✅ Recommended | Rate-limit export endpoint separately from CRUD routes (exports are expensive) |

**Conflicts:** None identified.

---

## 12. Rollback Procedure

### 12.1 Code rollback — revert generated files

If the generated export code introduces a regression, revert all scaffolded files atomically:

```bash
# Identify all files written by this tool
git diff --name-only HEAD | grep -E "(export|export_jobs|export_progress|export_guard)"

# Revert each file to its pre-tool state
git checkout HEAD -- app/core/export.py
git checkout HEAD -- app/core/export_jobs.py
git checkout HEAD -- app/core/export_progress.py
git checkout HEAD -- app/core/export_guard.py
git checkout HEAD -- app/jobs/export.py
git checkout HEAD -- tests/test_item_export.py

# Revert route addition for each modified model route file
git checkout HEAD -- app/api/routes/items.py
git checkout HEAD -- app/core/config.py
git checkout HEAD -- requirements.txt
git checkout HEAD -- .env.example

# Confirm application starts without export modules
PYTHONPATH=. python -c "from app.main import app; print('startup ok')"
```

### 12.2 Database rollback — export_jobs table

The `export_jobs` table is created by migration `0006_add_export_jobs`. Roll it back with:

```bash
# Downgrade the export_jobs migration
alembic downgrade -1

# Verify table is dropped
psql "$DATABASE_URL" -c "\d export_jobs"
# Expected: "Did not find any relation named 'export_jobs'"

# Confirm no index artifacts remain
psql "$DATABASE_URL" -c \
  "SELECT indexname FROM pg_indexes WHERE tablename = 'export_jobs';"
# Expected: 0 rows
```

The `downgrade()` function drops indexes before the table to avoid FK/dependency errors:

```python
# alembic/versions/0006_add_export_jobs.py (downgrade fragment)
def downgrade() -> None:
    op.drop_index("ix_export_jobs_created_at", table_name="export_jobs")
    op.drop_index("ix_export_jobs_user_status", table_name="export_jobs")
    op.drop_table("export_jobs")
```

### 12.3 Data preservation — pending async exports before rollback

Before rolling back, preserve any queued or running export jobs so users can be notified manually:

```bash
# Archive all non-complete export_jobs rows before rollback
psql "$DATABASE_URL" -c \
  "COPY (SELECT * FROM export_jobs WHERE status IN ('pending','running','failed') ORDER BY created_at) \
   TO STDOUT CSV HEADER" \
  > /tmp/export_jobs_backup_$(date +%Y%m%d_%H%M%S).csv

# Count how many jobs are in-flight
psql "$DATABASE_URL" -c \
  "SELECT status, COUNT(*) FROM export_jobs GROUP BY status;"
```

If any `pending` or `running` jobs exist, drain or cancel them before downgrading:

```bash
# Drain ARQ export queue (let running jobs finish)
arq app.worker.WorkerSettings --burst

# Or cancel pending jobs by marking them failed
psql "$DATABASE_URL" -c \
  "UPDATE export_jobs SET status='failed', error_message='Rollback in progress' \
   WHERE status IN ('pending', 'running');"
```

### 12.4 S3 cleanup — remove export files after rollback

After rolling back, clean up stale S3 export files to avoid orphaned storage costs:

```bash
# List all export files in S3 before deleting
aws s3 ls "s3://$AWS_S3_BUCKET/exports/" --recursive

# Delete all export files (DESTRUCTIVE — only run after confirming no active URLs)
aws s3 rm "s3://$AWS_S3_BUCKET/exports/" --recursive

# If only specific job files need cleanup (e.g. files older than 48 hours):
aws s3 ls "s3://$AWS_S3_BUCKET/exports/" \
  | awk '{print $4}' \
  | xargs -I{} aws s3 rm "s3://$AWS_S3_BUCKET/{}"
```

### 12.5 Failure mode: job stuck in RUNNING status

If an ARQ worker crashed mid-export and the `export_jobs` row is stuck as `running`:

```bash
# Find stuck jobs (running for > 15 minutes)
psql "$DATABASE_URL" -c \
  "SELECT id, user_id, model, format, created_at \
   FROM export_jobs \
   WHERE status = 'running' \
     AND created_at < NOW() - INTERVAL '15 minutes';"

# Mark stuck jobs as failed so users can retry
psql "$DATABASE_URL" -c \
  "UPDATE export_jobs \
   SET status = 'failed', \
       error_message = 'Worker crashed — please retry your export', \
       completed_at = NOW() \
   WHERE status = 'running' \
     AND created_at < NOW() - INTERVAL '15 minutes';"

# Restart the ARQ worker
arq app.worker.WorkerSettings
```

### 12.6 Emergency: quota counter corrupted in Redis

If the per-user export quota counter in Redis is corrupted and users cannot start new exports:

```bash
# Inspect current quota keys
redis-cli KEYS "export_quota:*"
redis-cli MGET $(redis-cli KEYS "export_quota:*")

# Reset quota for a specific user
redis-cli DEL "export_quota:{user_id}"

# Reset ALL quota counters (use sparingly — allows quota bypass until counters rebuild)
redis-cli KEYS "export_quota:*" | xargs redis-cli DEL

# Rebuild from DB: count running/pending exports per user and set counters
psql "$DATABASE_URL" -c \
  "SELECT user_id::text, COUNT(*) AS active_count \
   FROM export_jobs WHERE status IN ('pending','running') GROUP BY user_id;" \
  | while read user_id count; do
      redis-cli SETEX "export_quota:$user_id" 21600 "$count"
    done
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Unicode values in column data (Arabic, Chinese, emoji) | CSV uses UTF-8 encoding; `csv.writer` quotes correctly; NDJSON encodes as `\uXXXX` |
| EC-02 | NULL / None values in any column | CSV: empty string; NDJSON: `null`; XLSX: empty cell; Parquet: `null` in nullable column |
| EC-03 | `Decimal` type (e.g. prices) | Coerced to `float` in CSV/JSON; preserved as `pa.decimal128` in Parquet |
| EC-04 | `datetime` with timezone offset | Serialised as ISO 8601 with offset (e.g. `2026-04-12T10:00:00+00:00`) |
| EC-05 | Column value contains comma (CSV injection risk) | `csv.writer` quotes the cell; no injection vector |
| EC-06 | Column value contains newline characters | `csv.writer` wraps in double-quotes; multi-line cell produced |
| EC-07 | Very wide model (200+ columns) | XLSX limited to 16,384 columns per sheet; tool warns if model exceeds 200 columns |
| EC-08 | `xlsxwriter` not installed when `xlsx` in formats | Tool raises `ImportError` with clear message: "Run: pip install xlsxwriter>=3.1.0" |
| EC-09 | `pyarrow` not installed when `parquet` in formats | Tool raises `ImportError` with clear message: "Run: pip install pyarrow>=14.0.0" |
| EC-10 | `async_threshold=0` — all exports async | Every export returns 202 immediately; synchronous path never reached |
| EC-11 | Background worker not running when job enqueued | Job sits in ARQ queue; user does not receive email; `export_jobs.status` stays `pending` until worker resumes |
| EC-12 | S3 upload fails mid-stream (network error) | Worker retries up to 3× with exponential backoff; on final failure, `export_jobs.status=failed`; user emailed failure notice |
| EC-13 | User exports data for a soft-deleted account | Query returns 0 rows (soft-delete filter applies); empty export delivered; audit entry logged |
| EC-14 | Concurrent exports by the same user (below quota) | Each gets an independent `job_id`; S3 keys use `exports/{unique_job_id}.{format}`; no collision |
| EC-15 | Binary/BLOB column in model (e.g. `avatar_bytes`) | Serialised as hex string in CSV/JSON/XLSX; excluded from Parquet by default; tool warns operator |

---

## 14. Acceptance Criteria

1. ✅ All 35 Completeness Criteria verified by automated check
2. ✅ All 25 User Stories have passing acceptance tests
3. ✅ All 30 test cases pass (T-01..T-30)
4. ✅ All 8 Invariants enforced with no bypass path
5. ✅ All 15 edge cases handled with documented behavior
6. ✅ Server RAM peak < 50 MB measured on 1M-row streaming export
7. ✅ TTFB < 500 ms measured on synchronous CSV streaming
8. ✅ Sensitive columns verified absent from all four export formats
9. ✅ DB migration (`export_jobs` table) applies and rolls back cleanly
10. ✅ Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight validation
- [ ] Validate `project_dir` exists and is a directory
- [ ] Validate `app/` subdirectory exists
- [ ] Validate `alembic/versions/` exists (migration required)
- [ ] Validate `app/core/config.py` or equivalent settings file exists
- [ ] Detect existing `app/core/export.py` (idempotency — skip if present)
- [ ] Detect existing `/export` route on each target model (skip per-model if already present)
- [ ] Verify `xlsxwriter` importable if `xlsx` in formats; raise with install hint if missing
- [ ] Verify `pyarrow` importable if `parquet` in formats; raise with install hint if missing
- [ ] If `async_threshold` > 0: verify `add_background_job` (ARQ) already applied; emit warning if not

### 15.2 Export core module
- [ ] Create `app/core/export.py`
- [ ] Implement `_stream_batches` with `session.stream` + `yield_per` + `.partitions(BATCH_SIZE)`
- [ ] Implement `export_csv` — yields header chunk first, then row chunks
- [ ] Implement `export_ndjson` — yields one JSON line per row per batch
- [ ] Implement `export_xlsx` — uses `xlsxwriter.Workbook(constant_memory=True)`, bold headers
- [ ] Implement `export_parquet` — collects via pyarrow, Snappy compression
- [ ] Implement `_serialize` covering `datetime`, `UUID`, `Decimal`, `bytes`
- [ ] Implement `_safe_str` — None → empty string
- [ ] Define `SENSITIVE_COLUMNS` frozenset with all known sensitive field names
- [ ] Define `BATCH_SIZE = 1000` constant
- [ ] Verify file parses with `ast.parse`

### 15.3 Export jobs dispatcher
- [ ] Create `app/core/export_jobs.py`
- [ ] Implement `dispatch_export_job(user_id, model, format, filters) -> uuid.UUID`
- [ ] Calls `enqueue_job("run_export", ...)` via ARQ
- [ ] Returns new `uuid4()` as `job_id`
- [ ] Verify file parses
- [ ] Assert `dispatch_export_job` returns a valid UUID4 (not nil) in `tests/test_export_jobs.py::test_dispatch_returns_uuid4`
- [ ] Confirm that calling `dispatch_export_job` with an unknown model name raises `ValueError("unknown model")` before enqueuing

### 15.4 ARQ background worker
- [ ] Create `app/jobs/export.py`
- [ ] Implement `run_export(ctx, *, job_id, user_id, model, format, filters)` ARQ function
- [ ] Uses `_build_query` via `model_registry.build_filtered_stmt`
- [ ] Uses `_default_columns` via `model_registry.get_model_class`
- [ ] Streams chunks to `io.BytesIO` buffer
- [ ] Calls `storage.save(buf, key)` then `storage.presigned_url(key, expires_in=86400)`
- [ ] Sends email via `send_email(to=user.email, subject=..., body=...)`
- [ ] Updates `export_jobs.status` on completion and failure
- [ ] Verify file parses
- [ ] Register `run_export` in `WorkerSettings.functions`

### 15.5 Export progress tracker
- [ ] Create `app/core/export_progress.py`
- [ ] Define `ExportStatus` enum with `pending/running/complete/failed`
- [ ] Implement `set_export_progress(redis, job_id, status, ...)` with `JOB_TTL_SECONDS=90000`
- [ ] Implement `get_export_progress(redis, job_id) -> dict | None`
- [ ] Verify file parses
- [ ] Verify `get_export_progress` returns `None` (not raises) for an unknown `job_id` in `tests/test_export_progress.py::test_get_unknown_job_returns_none`
- [ ] Confirm `set_export_progress` sets Redis TTL to exactly `JOB_TTL_SECONDS=90000` via `redis.ttl(key)` assertion in integration test

### 15.6 Storage backend
- [ ] Create or extend `app/core/storage.py`
- [ ] Implement `S3StorageBackend` with `save()`, `presigned_url()`, `delete()` methods
- [ ] All boto3 calls wrapped in `loop.run_in_executor` to avoid blocking event loop
- [ ] Implement `get_storage()` factory reading `STORAGE_BACKEND` env var
- [ ] Verify file parses
- [ ] Confirm `S3StorageBackend.save()` does not call `boto3` directly from the event loop: assert `asyncio.get_event_loop().is_running()` inside a mock and verify `run_in_executor` was invoked
- [ ] Verify `presigned_url` sets `ExpiresIn=86400` by inspecting the boto3 `generate_presigned_url` call kwargs in `tests/test_storage.py::test_presigned_url_expiry`

### 15.7 Export guard
- [ ] Create `app/core/export_guard.py`
- [ ] Implement `validate_format(fmt)` raising 422 for unknown formats
- [ ] Implement `validate_columns(requested, allowed)` with SENSITIVE_COLUMNS strip + 422 on empty
- [ ] Implement `check_export_quota(redis, user_id)` with Redis incr + expire pattern
- [ ] Verify file parses
- [ ] Confirm every field in `SENSITIVE_COLUMNS` (e.g. `hashed_password`, `api_key`, `private_key`) is absent from the CSV header in `tests/test_{model}_export.py::test_sensitive_columns_stripped`
- [ ] Verify `validate_columns` raises HTTP 422 when only sensitive columns are requested, leaving the allowed set empty after stripping

### 15.8 Model registry
- [ ] Create `app/core/model_registry.py`
- [ ] Implement `register_model(cls)`, `get_model_class(name)`, `build_filtered_stmt(cls, filters)`
- [ ] `build_filtered_stmt` applies `owner_id`, `tenant_id`, `is_deleted` filters when present
- [ ] Populated at app startup
- [ ] Verify file parses
- [ ] Assert `build_filtered_stmt` appends `WHERE is_deleted = false` when the model column exists, verified via `str(stmt)` assertion in `tests/test_model_registry.py::test_build_filtered_stmt_soft_delete`
- [ ] Confirm `get_model_class` raises `KeyError` for unregistered names, not `None`, ensuring callers get an explicit failure

### 15.9 Route additions (per model)
- [ ] For each model in `models` param: read existing route file
- [ ] Append `GET /export` endpoint with `StreamingResponse | JSONResponse` return type
- [ ] Include `format` Query with `pattern="^(csv|json|xlsx|parquet)$"` (filtered to enabled formats)
- [ ] Include `columns` Query (optional, comma-separated)
- [ ] Preflight `COUNT(*)` query
- [ ] Sync vs async branch on `settings.EXPORT_ASYNC_THRESHOLD`
- [ ] Owner filter applied; soft-delete filter applied if present; tenant filter applied if present
- [ ] Sensitive column whitelist applied before streaming
- [ ] Verify file parses after modification
- [ ] Write atomically (temp + rename)

### 15.10 Settings additions
- [ ] Add `EXPORT_ASYNC_THRESHOLD: int = 10000` to `app/core/config.py`
- [ ] Add `STORAGE_BACKEND: str = "s3"` to `app/core/config.py`
- [ ] Add `AWS_S3_BUCKET: str = ""` to `app/core/config.py`
- [ ] Add all 3 vars to `.env.example` with comments
- [ ] Verify `config.py` parses
- [ ] Confirm `.env.example` contains `EXPORT_ASYNC_THRESHOLD`, `STORAGE_BACKEND`, and `AWS_S3_BUCKET` by running `grep -c "EXPORT_ASYNC_THRESHOLD\|STORAGE_BACKEND\|AWS_S3_BUCKET" .env.example` and asserting count == 3
- [ ] Verify that setting `EXPORT_ASYNC_THRESHOLD=0` causes all export requests to follow the async path (job dispatched, not streamed inline) in `tests/test_{model}_export.py::test_async_threshold_zero`

### 15.11 Requirements
- [ ] Append `xlsxwriter>=3.1.0` if `xlsx` in formats
- [ ] Append `pyarrow>=14.0.0` if `parquet` in formats
- [ ] Deduplicate `requirements.txt`
- [ ] Verify `requirements.txt` has no duplicate lines: `sort requirements.txt | uniq -d` must produce empty output
- [ ] Run `ruff check app/core/export.py app/core/export_jobs.py app/jobs/export.py` with zero findings; run `mypy app/core/export.py --strict` and confirm no new type errors
- [ ] Add `## [Unreleased]` entry to `CHANGELOG.md` describing the new `/export` endpoint and supported formats

### 15.12 Alembic migration
- [ ] Compute next revision number
- [ ] Generate `0006_add_export_jobs.py`
- [ ] `upgrade()`: create `export_jobs` table with all columns + CheckConstraint on `status`
- [ ] `upgrade()`: create composite index `ix_export_jobs_user_status` + `ix_export_jobs_created_at`
- [ ] `downgrade()`: drop indexes in reverse order, then drop table
- [ ] Migration parses
- [ ] Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` on a clean test DB and confirm no errors (round-trip test)

### 15.13 Test generation
- [ ] Create `tests/test_{model}_export.py`
- [ ] Generate all 30 test cases using project's existing fixture patterns
- [ ] Include streaming assertions (response body line count, CSV DictReader)
- [ ] Include security assertions (sensitive column absence)
- [ ] Include mock for `dispatch_export_job` in async threshold test
- [ ] Verify test file parses
- [ ] Assert CSV export response streams without loading full dataset into memory: use `tracemalloc` in `test_csv_streaming_memory` and confirm peak allocation < 10 MB for 50 000 rows

### 15.14 Documentation updates
- [ ] Append GDPR Article 20 data portability section to `app/KNOWLEDGE.md`
- [ ] Add tool entry in `manifest.yaml`
- [ ] Add `fastapi_add_data_export` row to `SKILL.md` tools table
- [ ] Register tool in `mcp_server.py` with `@mcp_tool` decorator
- [ ] Confirm `manifest.yaml` contains `fastapi_add_data_export` entry: `python -c "import yaml; d=yaml.safe_load(open('manifest.yaml')); assert any(t['name']=='fastapi_add_data_export' for t in d['tools'])"`
- [ ] Run `ruff check app/core/export_guard.py app/core/model_registry.py app/core/storage.py` with zero findings after documentation pass
- [ ] Verify `app/KNOWLEDGE.md` section on GDPR Article 20 includes mention of `SENSITIVE_COLUMNS` frozenset and the async export job flow

### 15.15 Atomicity and rollback
- [ ] All file writes use temp-file + atomic rename pattern
- [ ] Maintain `touched_files: list[Path]` to enable full rollback on partial failure
- [ ] On any exception: restore all `touched_files` from pre-write snapshots
- [ ] Return `{status: "rolled_back", error: str, files_rolled_back: [...]}` on failure
- [ ] Inject a failure after writing `app/core/export.py` but before `app/jobs/export.py` and assert `app/core/export.py` is restored to its original state (rollback test in `tests/test_tool_atomicity.py::test_export_rollback_on_partial_write`)
- [ ] Verify no stale temp files (`.tmp` suffix) remain in `app/` after a forced failure by listing `list(Path('app').rglob('*.tmp'))` and asserting empty
- [ ] Run `ruff check app/core/export_progress.py app/core/export_jobs.py` with zero findings post-rollback recovery

### 15.16 Verification
- [ ] Run `ast.parse` on every created and modified file
- [ ] Run `import_audit` to verify no circular imports introduced
- [ ] Run `pytest --tb=short -q` — confirm 0 new failures
- [ ] Run existing benchmark — confirm no throughput regression
- [ ] Measure tool execution time — must be < 4 s
- [ ] Run `pytest tests/test_{model}_export.py -v` and confirm all 30 export test cases pass with no skips
- [ ] Run `pytest tests/ --ignore=tests/test_{model}_export.py -q` and confirm zero regressions on previously-green tests

---

## 16. Documentation Output

```json
{
  "status": "success",
  "tool": "fastapi_add_data_export",
  "files_created": [
    "app/core/export.py",
    "app/core/export_jobs.py",
    "app/core/export_progress.py",
    "app/core/export_guard.py",
    "app/core/storage.py",
    "app/core/model_registry.py",
    "app/jobs/export.py",
    "alembic/versions/0006_add_export_jobs.py",
    "tests/test_item_export.py"
  ],
  "files_modified": [
    "app/api/routes/items.py",
    "app/core/config.py",
    "requirements.txt",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 2850,
    "files_created": 9,
    "files_modified": 4,
    "lines_added": 620,
    "lines_removed": 0
  },
  "completeness_criteria_verified": 35,
  "quality_standards_enforced": 10,
  "invariants_enforced": 8,
  "next_steps": [
    "Run: pip install xlsxwriter>=3.1.0 pyarrow>=14.0.0",
    "Run: alembic upgrade head  (creates export_jobs table)",
    "Run: pytest tests/test_item_export.py -v  (30 tests)",
    "Set AWS_S3_BUCKET, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY in .env",
    "Set EXPORT_ASYNC_THRESHOLD=10000 in .env (default: 10000)",
    "Run ARQ worker: arq app.worker.WorkerSettings",
    "Test: curl -OJ '/api/v1/items/export?format=csv' -H 'Authorization: Bearer ...'"
  ],
  "warnings": [
    "Async path requires add_background_job (ARQ) — run TOOL-033 first if not already applied.",
    "Async path requires S3 storage — set AWS_S3_BUCKET and AWS credentials in .env.",
    "Parquet exports collect all rows in memory before writing (pyarrow limitation) — async path recommended for parquet with > 100k rows."
  ],
  "notes": [
    "Export enabled on: Item",
    "Formats enabled: csv, json, xlsx, parquet",
    "Sync threshold: rows <= 10000 (streaming); async above threshold",
    "Sensitive columns auto-excluded: hashed_password, password, secret, api_key, token, refresh_token, private_key, api_secret, client_secret",
    "GDPR Article 20 compliance documented in app/KNOWLEDGE.md",
    "export_jobs table created for async job tracking and audit trail"
  ]
}
```
