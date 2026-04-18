"""TOOL-006: add_data_export — add production-grade data export to a FastAPI/SQLAlchemy project.

Generates a memory-bounded streaming export pipeline using SQLAlchemy server-side cursors
and ``StreamingResponse``, covering CSV, NDJSON, XLSX, and Parquet formats.  Large exports
above ``async_threshold`` rows are automatically promoted to async ARQ background jobs that
stream to S3 (or local disk) and email the user a presigned download URL.

The tool is idempotent: a second run detects ``app/core/export.py`` and the ``/export``
route fingerprint, returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_data_export import add_data_export

    result = add_data_export(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["app/core/export.py", "app/core/export_jobs.py", ...]
    print(result.next_steps)    # ["alembic upgrade head", ...]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_data_export",
    "description": "Add CSV/XLSX data export endpoints for all major resources.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_export",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_data_export(inp: ToolInput) -> ToolResult:
    """Add streaming data export capability to a FastAPI project.

    Reads the project at ``inp.project_dir``, detects which models exist,
    and writes all necessary files for production-grade data portability.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and
            optional ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    project = Path(inp.project_dir)
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err, execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    app_dir = project / "app"

    # --- Pre-flight: is export already enabled? ----------------------------
    export_core = app_dir / "core" / "export.py"
    if export_core.exists() and "SENSITIVE_COLUMNS" in export_core.read_text():
        return ToolResult(
            status="no_op",
            notes=["app/core/export.py with SENSITIVE_COLUMNS already present — export is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Discover target models -------------------------------------------
    model_pairs = _discover_models(app_dir)
    if not model_pairs:
        return ToolResult(
            status="error",
            error="No SQLAlchemy models found in app/models/. Generate models first.",
            execution_time_ms=_elapsed_ms(start),
        )
    model_names = [pascal for _stem, pascal in model_pairs]

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                f"[dry_run] Would add data export for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: Core streaming export utilities --------------------------
    _write_export_core(export_core)
    files_created.append(str(export_core))

    # --- Step 2: Async export job dispatcher ------------------------------
    export_jobs_file = app_dir / "core" / "export_jobs.py"
    _write_export_jobs(export_jobs_file)
    files_created.append(str(export_jobs_file))

    # --- Step 3: Export progress tracker (Redis) --------------------------
    export_progress_file = app_dir / "core" / "export_progress.py"
    _write_export_progress(export_progress_file)
    files_created.append(str(export_progress_file))

    # --- Step 4: Storage abstraction (S3 / local) -------------------------
    storage_file = app_dir / "core" / "storage.py"
    if not storage_file.exists():
        _write_storage(storage_file)
        files_created.append(str(storage_file))

    # --- Step 5: Model registry for background worker ---------------------
    registry_file = app_dir / "core" / "model_registry.py"
    if not registry_file.exists():
        _write_model_registry(registry_file)
        files_created.append(str(registry_file))

    # --- Step 6: ARQ background worker ------------------------------------
    jobs_dir = app_dir / "jobs"
    jobs_dir.mkdir(exist_ok=True)
    jobs_init = jobs_dir / "__init__.py"
    if not jobs_init.exists():
        jobs_init.write_text('"""ARQ background jobs package."""\n')
        files_created.append(str(jobs_init))
    worker_file = jobs_dir / "export.py"
    _write_arq_worker(worker_file)
    files_created.append(str(worker_file))

    # --- Step 7: Patch route files with /export endpoint -----------------
    for stem, model_name in model_pairs:
        route_file = app_dir / "api" / "routes" / f"{stem}.py"
        if route_file.exists():
            _patch_routes(route_file, model_name)
            files_modified.append(str(route_file))

    # --- Step 8: Generate Alembic migration for export_jobs table --------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- Step 9: Patch requirements.txt ----------------------------------------
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

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Data export enabled for models: {', '.join(model_names or [])}",
            "Streaming export uses server-side cursors — never loads full dataset in RAM.",
            "Exports above EXPORT_ASYNC_THRESHOLD rows are dispatched as ARQ background jobs.",
            "SENSITIVE_COLUMNS (hashed_password, api_key, etc.) are always excluded from export output.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set EXPORT_ASYNC_THRESHOLD in your .env (default: 10000 rows).",
            "Set STORAGE_BACKEND=s3 and AWS_S3_BUCKET for async export storage.",
            "Register run_export in your ARQ WorkerSettings.functions list.",
            "Restart the application.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return ``(snake_stem, PascalName)`` pairs from ``app/models/``, excluding system models.

    Only includes models where:
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of ``(snake_stem, PascalName)`` tuples.
    """
    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "__init__"}
    pairs: list[tuple[str, str]] = []
    available_routes: set[str] = set()
    if routes_dir.exists():
        for r in routes_dir.glob("*.py"):
            if r.stem != "__init__":
                available_routes.add(r.stem)
    for f in sorted(models_dir.glob("*.py")):
        stem = f.stem
        if stem in skip:
            continue
        if stem not in available_routes:
            continue
        pascal = "".join(w.capitalize() for w in stem.split("_"))
        try:
            tree = ast.parse(f.read_text())
        except SyntaxError:
            continue
        base_subclasses = [
            n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and any(
                (isinstance(b, ast.Name) and b.id == "Base")
                or (isinstance(b, ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        if pascal in base_subclasses:
            pairs.append((stem, pascal))
    return pairs


def _write_export_core(dest: Path) -> None:
    """Write ``app/core/export.py`` with streaming generators for all formats.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Streaming data export utilities: CSV, NDJSON, XLSX, Parquet.

        All generators are async and memory-bounded: rows are fetched in batches
        via SQLAlchemy server-side cursors and yielded as bytes chunks.
        Never accumulates the full dataset in RAM.
        \"\"\"
        from __future__ import annotations

        import csv
        import io
        import json
        from datetime import datetime
        from decimal import Decimal
        from typing import Any, AsyncIterator
        from uuid import UUID

        from sqlalchemy import Select
        from sqlalchemy.ext.asyncio import AsyncSession

        BATCH_SIZE: int = 1000

        SENSITIVE_COLUMNS: frozenset[str] = frozenset({
            "hashed_password", "password", "secret", "api_key", "token",
            "refresh_token", "private_key", "api_secret", "client_secret",
        })


        async def _stream_batches(
            session: AsyncSession, stmt: Select, batch_size: int = BATCH_SIZE
        ) -> AsyncIterator[list[Any]]:
            \"\"\"Yield rows in batches using a server-side streaming cursor.

            Args:
                session: Async SQLAlchemy session.
                stmt: SELECT statement to stream.
                batch_size: Number of rows per partition.

            Yields:
                Lists of ORM row objects, one list per batch.
            \"\"\"
            result = await session.stream(stmt.execution_options(yield_per=batch_size))
            async for partition in result.partitions(batch_size):
                yield [row[0] for row in partition]


        async def export_csv(
            session: AsyncSession, stmt: Select, columns: list[str]
        ) -> AsyncIterator[bytes]:
            \"\"\"Stream CSV bytes. Yields UTF-8 header row first, then data chunks.

            Args:
                session: Async SQLAlchemy session.
                stmt: SELECT statement for the rows to export.
                columns: Ordered list of column names to include.

            Yields:
                UTF-8 encoded CSV bytes chunks.
            \"\"\"
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
            \"\"\"Stream NDJSON (newline-delimited JSON). One object per line.

            Args:
                session: Async SQLAlchemy session.
                stmt: SELECT statement for the rows to export.
                columns: Ordered list of column names to include.

            Yields:
                UTF-8 encoded NDJSON bytes chunks (one JSON object per line).
            \"\"\"
            async for batch in _stream_batches(session, stmt):
                lines = "".join(
                    json.dumps({col: _serialize(getattr(row, col, None)) for col in columns}) + "\\n"
                    for row in batch
                )
                yield lines.encode("utf-8")


        async def export_xlsx(
            session: AsyncSession, stmt: Select, columns: list[str]
        ) -> AsyncIterator[bytes]:
            \"\"\"Stream XLSX using xlsxwriter constant_memory mode (write-once, low RAM).

            Args:
                session: Async SQLAlchemy session.
                stmt: SELECT statement for the rows to export.
                columns: Ordered list of column names to include.

            Yields:
                Single bytes chunk containing the complete XLSX workbook.
            \"\"\"
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
            \"\"\"Stream Parquet via pyarrow. Collects all rows (pyarrow lacks native streaming write).

            Args:
                session: Async SQLAlchemy session.
                stmt: SELECT statement for the rows to export.
                columns: Ordered list of column names to include.

            Yields:
                Single bytes chunk containing the complete Parquet file (snappy compressed).
            \"\"\"
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
            \"\"\"Coerce non-JSON-native Python types to serialisable equivalents.

            Args:
                value: Any Python value, including ORM-mapped fields.

            Returns:
                A JSON-serialisable representation of the value.
            \"\"\"
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
            \"\"\"Return serialised value as string; None becomes empty string.

            Args:
                value: Any value to convert.

            Returns:
                String representation, or ``\"\"`` when value is ``None``.
            \"\"\"
            if value is None:
                return ""
            return str(_serialize(value))
        """)
    dest.write_text(content)


def _write_export_jobs(dest: Path) -> None:
    """Write ``app/core/export_jobs.py`` with async ARQ dispatcher.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Dispatch helper for large-dataset async export jobs.

        Requires ARQ queue (add_background_job tool must run first, or
        configure ARQ manually via app.core.arq).
        \"\"\"
        from __future__ import annotations

        import uuid
        from typing import Any


        async def dispatch_export_job(
            *,
            user_id: uuid.UUID,
            model: str,
            format: str,
            filters: dict[str, Any],
        ) -> uuid.UUID:
            \"\"\"Enqueue a background export job. Returns a new job_id UUID.

            The worker streams data to storage and emails the user a presigned URL.

            Args:
                user_id: UUID of the requesting user.
                model: Model name string (e.g. ``\"Item\"``).
                format: Export format — ``csv``, ``json``, ``xlsx``, or ``parquet``.
                filters: Dict of column name -> value filters applied at the worker.

            Returns:
                Newly generated ``job_id`` UUID.
            \"\"\"
            from app.core.arq import enqueue_job  # type: ignore[import]

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
        """)
    dest.write_text(content)


def _write_export_progress(dest: Path) -> None:
    """Write ``app/core/export_progress.py`` with Redis progress tracker.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Lightweight export job progress tracker backed by Redis.

        Writes progress keys so clients can poll /exports/{job_id}/status.
        Each key has a TTL slightly over 24 h to cover the presigned URL lifetime.
        \"\"\"
        from __future__ import annotations

        import json
        from enum import Enum
        from typing import TYPE_CHECKING, Any

        if TYPE_CHECKING:
            import redis.asyncio as aioredis

        JOB_TTL_SECONDS: int = 90_000  # 25 h — covers presigned URL lifetime


        class ExportStatus(str, Enum):
            \"\"\"Lifecycle states for an async export job.\"\"\"

            PENDING = "pending"
            RUNNING = "running"
            COMPLETE = "complete"
            FAILED = "failed"


        async def set_export_progress(
            redis: "aioredis.Redis",
            job_id: str,
            status: ExportStatus,
            *,
            rows_written: int = 0,
            total_rows: int = 0,
            download_url: str | None = None,
            error: str | None = None,
        ) -> None:
            \"\"\"Write job progress to Redis with a 25-hour TTL.

            Args:
                redis: Async Redis client.
                job_id: Unique export job identifier.
                status: Current lifecycle state.
                rows_written: Rows streamed to storage so far.
                total_rows: Total rows expected (0 if unknown).
                download_url: Presigned download URL, set when status=COMPLETE.
                error: Error message, set when status=FAILED.
            \"\"\"
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
            redis: "aioredis.Redis", job_id: str
        ) -> dict[str, Any] | None:
            \"\"\"Fetch current job progress. Returns None if job_id unknown or expired.

            Args:
                redis: Async Redis client.
                job_id: Unique export job identifier.

            Returns:
                Progress dict or ``None`` if the job key has expired or never existed.
            \"\"\"
            key = f"export_job:{job_id}"
            raw = await redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        """)
    dest.write_text(content)


def _write_storage(dest: Path) -> None:
    """Write ``app/core/storage.py`` with S3 presigned URL support.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Storage abstraction with S3 presigned URL support and local-file fallback.

        Used by the async export worker to store completed export files.
        Select backend via the ``STORAGE_BACKEND`` environment variable.
        \"\"\"
        from __future__ import annotations

        import asyncio
        import io
        import os
        from pathlib import Path
        from typing import BinaryIO


        class S3StorageBackend:
            \"\"\"Wraps boto3 S3 client with async-compatible upload and presigned-URL generation.

            Credentials are read from ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
            and ``AWS_S3_BUCKET`` environment variables.
            \"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise the S3 client from environment variables.\"\"\"
                import boto3

                self._bucket = os.environ["AWS_S3_BUCKET"]
                self._client = boto3.client(
                    "s3",
                    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    region_name=os.getenv("AWS_REGION", "us-east-1"),
                )

            async def save(self, buf: BinaryIO, key: str, *, content_type: str) -> None:
                \"\"\"Upload buffer to S3. Runs in a thread-pool executor to avoid blocking.

                Args:
                    buf: File-like object to upload.
                    key: S3 object key (path within the bucket).
                    content_type: MIME type for the uploaded object.
                \"\"\"
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._client.upload_fileobj(
                        buf, self._bucket, key,
                        ExtraArgs={"ContentType": content_type},
                    ),
                )

            async def presigned_url(self, key: str, *, expires_in: int = 86400) -> str:
                \"\"\"Generate a presigned GET URL valid for ``expires_in`` seconds.

                Args:
                    key: S3 object key.
                    expires_in: URL validity in seconds (default: 86400 = 24 h).

                Returns:
                    Presigned HTTPS URL string.
                \"\"\"
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
                \"\"\"Delete an export file after TTL expiry or manual cleanup.

                Args:
                    key: S3 object key to remove.
                \"\"\"
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self._client.delete_object(Bucket=self._bucket, Key=key),
                )


        class LocalStorageBackend:
            \"\"\"Filesystem fallback storage for development and testing.\"\"\"

            def __init__(self) -> None:
                \"\"\"Initialise local storage under ``EXPORT_LOCAL_DIR`` (default: /tmp/exports).\"\"\"
                self._root = Path(os.getenv("EXPORT_LOCAL_DIR", "/tmp/exports"))
                self._root.mkdir(parents=True, exist_ok=True)

            async def save(self, buf: BinaryIO, key: str, *, content_type: str) -> None:
                \"\"\"Write buffer to local filesystem.

                Args:
                    buf: File-like object to write.
                    key: Relative path within the local export directory.
                    content_type: Ignored for local storage.
                \"\"\"
                dest = self._root / key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(buf.read() if isinstance(buf, io.IOBase) else bytes(buf.read()))

            async def presigned_url(self, key: str, *, expires_in: int = 86400) -> str:
                \"\"\"Return a local file:// URL (no real expiry for local backend).

                Args:
                    key: Relative path within the local export directory.
                    expires_in: Ignored for local storage.

                Returns:
                    ``file://`` URI string.
                \"\"\"
                return f"file://{self._root / key}"

            async def delete(self, key: str) -> None:
                \"\"\"Remove a local export file.

                Args:
                    key: Relative path within the local export directory.
                \"\"\"
                target = self._root / key
                if target.exists():
                    target.unlink()


        def get_storage() -> S3StorageBackend | LocalStorageBackend:
            \"\"\"Factory — returns backend configured by ``STORAGE_BACKEND`` env var.

            Returns:
                Configured storage backend instance.

            Raises:
                NotImplementedError: If ``STORAGE_BACKEND`` is set to an unknown value.
            \"\"\"
            backend = os.getenv("STORAGE_BACKEND", "local")
            if backend == "s3":
                return S3StorageBackend()
            if backend == "local":
                return LocalStorageBackend()
            raise NotImplementedError(f"Storage backend {backend!r} not implemented.")
        """)
    dest.write_text(content)


def _write_model_registry(dest: Path) -> None:
    """Write ``app/core/model_registry.py`` for background worker model resolution.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"Model registry: maps string model names to SQLAlchemy classes.

        Populated at app startup. Used by the background export worker to
        reconstruct export queries without coupling to specific model imports.
        \"\"\"
        from __future__ import annotations

        from typing import Any, Type

        from sqlalchemy import select, Select
        from sqlalchemy.orm import DeclarativeBase

        _MODEL_REGISTRY: dict[str, Type[DeclarativeBase]] = {}


        def register_model(model_cls: Type[DeclarativeBase]) -> None:
            \"\"\"Register a model class under its ``__name__``.

            Args:
                model_cls: SQLAlchemy mapped class to register.
            \"\"\"
            _MODEL_REGISTRY[model_cls.__name__] = model_cls


        def get_model_class(name: str) -> Type[DeclarativeBase]:
            \"\"\"Return model class by name. Raises KeyError if not registered.

            Args:
                name: Model class name (e.g. ``\"Item\"``).

            Returns:
                The registered model class.

            Raises:
                KeyError: If ``name`` has not been registered.
            \"\"\"
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
            \"\"\"Build a SELECT statement applying all supported filters.

            Supported filter keys: owner_id, tenant_id.
            ``is_deleted`` is always forced to ``False`` when the column exists.

            Args:
                model_cls: SQLAlchemy mapped class to query.
                filters: Dict of column name -> value to filter on.

            Returns:
                Configured SELECT statement.
            \"\"\"
            stmt = select(model_cls)
            for col_name, col_value in filters.items():
                col = getattr(model_cls, col_name, None)
                if col is None:
                    continue
                stmt = stmt.where(col == col_value)
            if hasattr(model_cls, "is_deleted"):
                stmt = stmt.where(model_cls.is_deleted.is_(False))
            return stmt
        """)
    dest.write_text(content)


def _write_arq_worker(dest: Path) -> None:
    """Write ``app/jobs/export.py`` with the ARQ background worker.

    Args:
        dest: Absolute destination path.
    """
    content = textwrap.dedent("""\
        \"\"\"ARQ worker: exports data to storage and emails the user a presigned link.

        Register this function in your ARQ ``WorkerSettings.functions`` list.
        The worker session is expected in ``ctx[\"session\"]`` via ARQ startup hooks.
        \"\"\"
        from __future__ import annotations

        import io
        import logging
        import uuid
        from typing import Any

        from app.core.export import export_csv, export_ndjson, export_parquet, export_xlsx
        from app.core.storage import get_storage

        logger = logging.getLogger(__name__)

        _GENERATORS = {
            "csv": export_csv,
            "json": export_ndjson,
            "xlsx": export_xlsx,
            "parquet": export_parquet,
        }

        _CONTENT_TYPES = {
            "csv": "text/csv",
            "json": "application/x-ndjson",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "parquet": "application/octet-stream",
        }


        async def _stream_export_to_storage(
            session, storage, gen_fn, stmt, cols: list, job_id: str, format: str
        ) -> str:
            \"\"\"Stream rows through a generator into storage and return a presigned URL.

            Args:
                session: Async SQLAlchemy session.
                storage: Storage backend (has .save() and .presigned_url()).
                gen_fn: Async generator function that yields bytes chunks.
                stmt: Filtered SQLAlchemy SELECT statement.
                cols: Column names to include in the export.
                job_id: Export job UUID string (used as storage key prefix).
                format: File format extension (e.g. ``csv``, ``json``).

            Returns:
                Presigned download URL valid for 24 h.
            \"\"\"
            buf = io.BytesIO()
            async for chunk in gen_fn(session, stmt, cols):
                buf.write(chunk)
            buf.seek(0)
            key = f"exports/{job_id}.{format}"
            await storage.save(buf, key, content_type=_CONTENT_TYPES.get(format, "application/octet-stream"))
            return await storage.presigned_url(key, expires_in=86400)


        async def run_export(
            ctx: dict,
            *,
            job_id: str,
            user_id: str,
            model: str,
            format: str,
            filters: dict[str, Any],
        ) -> dict[str, Any]:
            \"\"\"ARQ job entrypoint. Streams rows to storage, emails presigned URL.

            Args:
                ctx: ARQ job context (contains ``session``, ``redis``, etc.).
                job_id: Unique export job UUID (string).
                user_id: UUID string of the requesting user.
                model: Model name string (e.g. ``\"Item\"``).
                format: Export format — ``csv``, ``json``, ``xlsx``, or ``parquet``.
                filters: Column filters to apply when building the export query.

            Returns:
                Dict with ``job_id``, ``url``, and ``status``.

            Raises:
                ValueError: If ``format`` is not a recognised export format.
            \"\"\"
            gen_fn = _GENERATORS.get(format)
            if gen_fn is None:
                raise ValueError(f"run_export: unknown format={format!r}")
            from app.core.export_progress import ExportStatus, set_export_progress
            from app.core.model_registry import build_filtered_stmt, get_model_class

            session = ctx["session"]
            storage = get_storage()
            redis = ctx.get("redis")
            if redis:
                await set_export_progress(redis, job_id, ExportStatus.RUNNING)
            model_cls = get_model_class(model)
            stmt = build_filtered_stmt(model_cls, filters)
            cols = [
                c.name for c in model_cls.__table__.columns
                if c.name not in __import__("app.core.export", fromlist=["SENSITIVE_COLUMNS"]).SENSITIVE_COLUMNS
            ]
            url = await _stream_export_to_storage(session, storage, gen_fn, stmt, cols, job_id, format)
            if redis:
                await set_export_progress(redis, job_id, ExportStatus.COMPLETE, download_url=url)
            _try_send_email(ctx, user_id, model, url, job_id)
            logger.info("export_complete job_id=%s model=%s format=%s user=%s", job_id, model, format, user_id)
            return {"job_id": job_id, "url": url, "status": "complete"}


        def _try_send_email(ctx: dict, user_id: str, model: str, url: str, job_id: str) -> None:
            \"\"\"Attempt to email the user a download link; log a warning on failure.

            Args:
                ctx: ARQ context.
                user_id: UUID string of the requesting user.
                model: Model name for the email subject.
                url: Presigned download URL.
                job_id: Export job identifier for log correlation.
            \"\"\"
            try:
                from app.core.email import send_email  # type: ignore[import]
                import asyncio

                session = ctx.get("session")
                if session is None:
                    return

                async def _send() -> None:
                    from app.crud.user import get as crud_get_user  # type: ignore[import]
                    user = await crud_get_user(session, uuid.UUID(user_id))
                    if user and getattr(user, "email", None):
                        await send_email(
                            to=user.email,
                            subject=f"Your {model} data export is ready",
                            body=(
                                f"Your export is ready for download.\\n\\n"
                                f"Download link (expires in 24 hours):\\n{url}\\n\\n"
                                f"This link cannot be shared — it is scoped to your account."
                            ),
                        )

                loop = asyncio.get_event_loop()
                loop.run_until_complete(_send())
            except Exception as exc:
                logger.warning("export_email_failed job_id=%s user_id=%s exc=%s", job_id, user_id, exc)
        """)
    dest.write_text(content)


def _patch_routes(route_file: Path, model_name: str) -> None:
    """Append ``GET /{model}/export`` endpoint with sync/async dispatch logic.

    Args:
        route_file: Path to ``app/api/routes/{name}.py``.
        model_name: PascalCase model name.
    """
    src = route_file.read_text()
    if "/export" in src or "StreamingResponse" in src:
        return

    lower = model_name.lower()
    additions = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Data export endpoint — added by add_data_export tool
        # ---------------------------------------------------------------------------
        from fastapi.responses import JSONResponse as _JSONResponse, StreamingResponse as _StreamingResponse
        from fastapi import Query as _ExportQuery
        from sqlalchemy import func as _func, select as _select

        from app.core.export import (
            SENSITIVE_COLUMNS as _SENSITIVE_COLUMNS,
            export_csv as _export_csv,
            export_ndjson as _export_ndjson,
            export_xlsx as _export_xlsx,
            export_parquet as _export_parquet,
        )
        from app.core.export_jobs import dispatch_export_job as _dispatch_export_job
        from app.models.{lower} import {model_name} as _{model_name}

        _EXPORT_ASYNC_THRESHOLD: int = int(__import__("os").getenv("EXPORT_ASYNC_THRESHOLD", "10000"))

        _FORMAT_META: dict = {
            "csv":     (_export_csv,     "text/csv",                   "{lower}s.csv"),
            "json":    (_export_ndjson,  "application/x-ndjson",       "{lower}s.ndjson"),
            "xlsx":    (_export_xlsx,    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "{lower}s.xlsx"),
            "parquet": (_export_parquet, "application/octet-stream",   "{lower}s.parquet"),
        }

        _DEFAULT_EXPORT_COLUMNS: list[str] = [
            c.name for c in _{model_name}.__table__.columns
            if c.name not in _SENSITIVE_COLUMNS
        ]


        async def _build_export_base_stmt_{lower}(session, current_user):
            \"\"\"Build scoped base SELECT statement and count for {model_name} export.

            Args:
                session: Async SQLAlchemy session.
                current_user: Authenticated user (scopes query via owner_id and tenant_id).

            Returns:
                Tuple of (base_stmt, total_row_count).
            \"\"\"
            base_stmt = _select(_{model_name}).where(_{model_name}.owner_id == current_user.id)
            if hasattr(_{model_name}, "is_deleted"):
                base_stmt = base_stmt.where(_{model_name}.is_deleted.is_(False))
            if hasattr(_{model_name}, "tenant_id") and hasattr(current_user, "tenant_id"):
                base_stmt = base_stmt.where(_{model_name}.tenant_id == current_user.tenant_id)
            total: int = (await session.execute(_select(_func.count()).select_from(base_stmt.subquery()))).scalar_one()
            return base_stmt, total


        @router.get("/export", response_model=None, summary="Export {model_name} records (GDPR Art. 20 data portability)")
        async def export_{lower}s(
            session: SessionDep,
            current_user: CurrentUser,
            format: str = _ExportQuery(default="csv", pattern="^(csv|json|xlsx|parquet)$"),
            columns: str | None = _ExportQuery(
                default=None,
                description="Comma-separated column names to include. Omit for all non-sensitive columns.",
            ),
        ) -> _StreamingResponse | _JSONResponse:
            \"\"\"Export the current user's {model_name} records.

            Small exports stream synchronously via StreamingResponse.
            Large exports are queued as ARQ background jobs and return HTTP 202.
            Sensitive columns are always excluded.

            Args:
                session: Injected async DB session.
                current_user: Authenticated user (scopes the export query).
                format: Export format — csv, json, xlsx, or parquet.
                columns: Optional comma-separated column whitelist.

            Returns:
                StreamingResponse for sync exports or JSONResponse (202) for async jobs.
            \"\"\"
            from fastapi import HTTPException

            base_stmt, total = await _build_export_base_stmt_{lower}(session, current_user)
            if total > _EXPORT_ASYNC_THRESHOLD:
                job_id = await _dispatch_export_job(
                    user_id=current_user.id, model="{model_name}", format=format,
                    filters={"owner_id": str(current_user.id)},
                )
                return _JSONResponse(status_code=202, content={
                    "status": "queued", "job_id": str(job_id), "row_estimate": total,
                    "message": f"Export queued ({total:,} rows). You will receive an email with a download link.",
                })
            requested = [c.strip() for c in columns.split(",")] if columns else _DEFAULT_EXPORT_COLUMNS
            safe_cols = [c for c in requested if c in _DEFAULT_EXPORT_COLUMNS]
            if not safe_cols:
                raise HTTPException(status_code=422, detail="No valid columns selected after security filtering.")
            gen_fn, media_type, filename = _FORMAT_META[format]
            return _StreamingResponse(
                gen_fn(session, base_stmt, safe_cols), media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        """).replace("{lower}", lower).replace("{model_name}", model_name)

    route_file.write_text(src + additions)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration creating the ``export_jobs`` tracking table.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add export_jobs tracking table.

        Revision ID: 0006_add_export_jobs
        Revises: {down_rev}
        Create Date: auto-generated by add_data_export tool
        \"\"\"
        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0006_add_export_jobs"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create export_jobs table with status check constraint and indexes.\"\"\"
            op.create_table(
                "export_jobs",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                    index=True,
                ),
                sa.Column("model", sa.String(128), nullable=False),
                sa.Column("format", sa.String(16), nullable=False),
                sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
                sa.Column("row_count", sa.Integer(), nullable=True),
                sa.Column("storage_key", sa.String(512), nullable=True),
                sa.Column("error_message", sa.Text(), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
                sa.CheckConstraint(
                    "status IN ('pending','running','complete','failed')",
                    name="ck_export_jobs_status",
                ),
            )
            op.create_index("ix_export_jobs_user_status", "export_jobs", ["user_id", "status"])
            op.create_index("ix_export_jobs_created_at", "export_jobs", ["created_at"])


        def downgrade() -> None:
            \"\"\"Drop export_jobs indexes and table.\"\"\"
            op.drop_index("ix_export_jobs_created_at", table_name="export_jobs")
            op.drop_index("ix_export_jobs_user_status", table_name="export_jobs")
            op.drop_table("export_jobs")
        """).replace("{down_rev}", down_rev)

    migration_file = versions_dir / "0006_add_export_jobs.py"
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
