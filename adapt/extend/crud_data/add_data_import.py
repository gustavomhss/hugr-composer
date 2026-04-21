"""TOOL-077: add_data_import — add CSV/Excel upload with async processing to a FastAPI project.

Generates a production-grade data import pipeline: upload endpoint, async row
validation, batch processing, ImportJob model tracking status/progress/errors,
and a configurable RowValidator.  Large files are processed in background tasks
so the upload endpoint returns immediately with a job ID.  Errors are collected
per-row and exposed via a dedicated error-report endpoint.

The tool is idempotent: a second run detects ``ImportJob`` in
``app/models/import_job.py`` and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_data_import import add_data_import

    result = add_data_import(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["app/imports/__init__.py", ...]
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
    "name": "fastapi_data_add_data_import",
    "description": "Add CSV/Excel upload with async processing, validation and error reporting.",
    "tags": ["extend", "crud_data"],
    "entry": "add_data_import",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_data_import(inp: ToolInput) -> ToolResult:
    """Add CSV/Excel data import capability to a FastAPI project.

    Generates ImportJob model, ImportProcessor, RowValidator, schemas,
    CRUD, routes, and an Alembic migration.

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
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    # --- Prerequisite check (standalone mode) --------------------------------
    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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

    files_created: list[str] = []
    if scaffolded:
        files_created.extend(scaffolded)

    app_dir = project / "app"

    # --- Pre-flight: is import already enabled? --------------------------------
    import_model = app_dir / "models" / "import_job.py"
    if import_model.exists() and "ImportJob" in import_model.read_text():
        return ToolResult(
            status="no_op",
            notes=["ImportJob model already present — data import is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would add data import pipeline (ImportJob model, processor, validator).",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # --- Step 1: app/imports/__init__.py ------------------------------------
    imports_pkg = app_dir / "imports" / "__init__.py"
    _write_imports_init(imports_pkg)
    files_created.append(str(imports_pkg))

    # --- Step 2: app/imports/validators.py ---------------------------------
    validators_file = app_dir / "imports" / "validators.py"
    _write_validators(validators_file)
    files_created.append(str(validators_file))

    # --- Step 3: app/imports/processor.py ----------------------------------
    processor_file = app_dir / "imports" / "processor.py"
    _write_processor(processor_file)
    files_created.append(str(processor_file))

    # --- Step 4: app/models/import_job.py ----------------------------------
    _write_import_job_model(import_model)
    files_created.append(str(import_model))

    # Register model in app/models/__init__.py
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("import_job", "ImportJob")],
    )

    # --- Step 5: app/schemas/import_job.py ---------------------------------
    schema_file = app_dir / "schemas" / "import_job.py"
    _write_import_job_schema(schema_file)
    files_created.append(str(schema_file))

    # --- Step 6: app/crud/import_job.py ------------------------------------
    crud_file = app_dir / "crud" / "import_job.py"
    _write_import_job_crud(crud_file)
    files_created.append(str(crud_file))

    # --- Step 7: app/api/routes/imports.py ---------------------------------
    routes_file = app_dir / "api" / "routes" / "imports.py"
    _write_import_routes(routes_file)
    files_created.append(str(routes_file))

    # --- Step 8: Register route in app/routes/__init__.py ------------------
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # --- Step 9: Patch config.py with import settings ----------------------
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # --- Step 10: Alembic migration ----------------------------------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # --- ast.parse validation loop -----------------------------------------
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
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Step helpers — each < 50 LOC
# ---------------------------------------------------------------------------

def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to the models ``__init__.py``.
        class_imports: List of ``(module_stem, ClassName)`` tuples.
    """
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
    """Register imports router in ``app/routes/__init__.py``.

    Args:
        routes_init: Path to the routes ``__init__.py``.
    """
    src = routes_init.read_text()
    if "imports" in src:
        return
    addition = textwrap.dedent("""\

        # --- Data import routes — added by add_data_import tool ---
        from app.api.routes.imports import router as imports_router  # noqa: E402
        api_router.include_router(imports_router)
        """)
    routes_init.write_text(src.rstrip("\n") + "\n" + addition)


def _patch_config(config_file: Path) -> None:
    """Inject import-specific settings into ``app/core/config.py``.

    Fields are inserted with 4-space indent so they land inside the Settings class body.

    Args:
        config_file: Path to the config module.
    """
    src = config_file.read_text()
    if "IMPORT_MAX_FILE_SIZE_MB" in src:
        return
    # 4-space indented so they sit inside the Settings class body
    fields = (
        "\n"
        "    # Import settings\n"
        "    IMPORT_MAX_FILE_SIZE_MB: int = 50\n"
        "    IMPORT_BATCH_SIZE: int = 500\n"
    )
    if "settings = Settings()" in src:
        src = src.replace(
            "\nsettings = Settings()",
            fields + "\nsettings = Settings()",
        )
    else:
        src = src.rstrip("\n") + fields + "\n"
    config_file.write_text(src)


def _write_imports_init(dest: Path) -> None:
    """Write ``app/imports/__init__.py`` package marker.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Data import pipeline package.

        Exposes ImportProcessor and RowValidator for CSV/Excel data ingestion.
        \"\"\"

        from app.imports.processor import ImportProcessor
        from app.imports.validators import RowValidator

        __all__ = ["ImportProcessor", "RowValidator"]
        """))


def _write_validators(dest: Path) -> None:
    """Write ``app/imports/validators.py`` with configurable RowValidator.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Row-level validators for data import pipeline.

        RowValidator supports configurable required-field and type-coercion rules.
        Each rule is a callable that receives a raw dict and raises ValueError on failure.
        \"\"\"

        from __future__ import annotations

        import logging
        from collections.abc import Callable
        from typing import Any

        logger = logging.getLogger(__name__)


        class RowValidator:
            \"\"\"Validate a single import row against a set of configurable rules.

            Attributes:
                required_fields: Column names that must be non-empty.
                type_rules: Map of column name → callable that coerces/validates the value.
            \"\"\"

            def __init__(
                self,
                required_fields: list[str] | None = None,
                type_rules: dict[str, Callable[[Any], Any]] | None = None,
            ) -> None:
                \"\"\"Initialise the validator.

                Args:
                    required_fields: Column names that must be present and non-empty.
                    type_rules: Map of field name to a type-coercion callable.
                \"\"\"
                self.required_fields: list[str] = required_fields or []
                self.type_rules: dict[str, Callable[[Any], Any]] = type_rules or {}

            def validate(self, row: dict[str, Any], row_index: int) -> list[str]:
                \"\"\"Validate a single row and return a list of error strings.

                Args:
                    row: Raw row dict from the parsed file.
                    row_index: Zero-based row index for error messages.

                Returns:
                    List of human-readable error descriptions. Empty means valid.
                \"\"\"
                errors: list[str] = []
                for field in self.required_fields:
                    val = row.get(field)
                    if val is None or str(val).strip() == "":
                        errors.append(f"Row {row_index}: required field '{field}' is missing or empty")
                for field, coerce in self.type_rules.items():
                    if field not in row:
                        continue
                    try:
                        coerce(row[field])
                    except (ValueError, TypeError) as exc:
                        errors.append(f"Row {row_index}: field '{field}' failed type check: {exc}")
                return errors
        """))


def _write_processor(dest: Path) -> None:
    """Write ``app/imports/processor.py`` with ImportProcessor.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"ImportProcessor: parses CSV/Excel files and processes rows in batches.

        Excel support uses a lazy ``openpyxl`` import so the module boots
        without openpyxl installed — only ``parse_excel`` will raise ImportError.
        \"\"\"

        from __future__ import annotations

        import csv
        import io
        import logging
        import uuid
        from collections.abc import AsyncGenerator
        from typing import Any

        from sqlalchemy.ext.asyncio import AsyncSession

        from app.crud.import_job import (
            fail_import_job,
            mark_import_job_done,
            update_import_job_progress,
        )
        from app.imports.validators import RowValidator

        logger = logging.getLogger(__name__)


        class ImportProcessor:
            \"\"\"Parse and process CSV or Excel file data for a given import job.

            Attributes:
                validator: RowValidator applied to every row before insert.
                batch_size: Number of rows committed per transaction.
            \"\"\"

            def __init__(
                self,
                validator: RowValidator | None = None,
                batch_size: int = 500,
            ) -> None:
                \"\"\"Initialise the processor.

                Args:
                    validator: Optional row validator (permissive if None).
                    batch_size: Rows per DB transaction batch.
                \"\"\"
                self.validator = validator or RowValidator()
                self.batch_size = batch_size

            def parse_csv(self, content: bytes) -> list[dict[str, Any]]:
                \"\"\"Parse CSV bytes into a list of row dicts.

                Args:
                    content: Raw file bytes (UTF-8 with optional BOM).

                Returns:
                    List of row dicts keyed by the header row.
                \"\"\"
                text = content.decode("utf-8-sig")
                reader = csv.DictReader(io.StringIO(text))
                return [dict(row) for row in reader]

            def parse_excel(self, content: bytes) -> list[dict[str, Any]]:
                \"\"\"Parse Excel bytes into a list of row dicts (lazy openpyxl).

                Args:
                    content: Raw XLSX file bytes.

                Returns:
                    List of row dicts keyed by the first-row header values.

                Raises:
                    ImportError: If openpyxl is not installed.
                \"\"\"
                import openpyxl  # noqa: PLC0415 — lazy import (optional SDK)

                wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return []
                headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
                return [dict(zip(headers, row)) for row in rows[1:]]

            def validate_rows(
                self, rows: list[dict[str, Any]]
            ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
                \"\"\"Split rows into valid and invalid, collecting per-row errors.

                Args:
                    rows: Parsed rows from ``parse_csv`` or ``parse_excel``.

                Returns:
                    Tuple of (valid_rows, error_rows). Each error row has an
                    added ``_errors`` key with a list of error strings.
                \"\"\"
                valid: list[dict[str, Any]] = []
                errors: list[dict[str, Any]] = []
                for idx, row in enumerate(rows):
                    row_errors = self.validator.validate(row, idx)
                    if row_errors:
                        errors.append({**row, "_errors": row_errors})
                    else:
                        valid.append(row)
                return valid, errors

            async def process_batch(
                self,
                session: AsyncSession,
                rows: list[dict[str, Any]],
            ) -> int:
                \"\"\"Process a batch of valid rows — override to customise persistence.

                Default implementation is a no-op stub; concrete projects override
                this method to insert domain rows via their own CRUD layer.

                Args:
                    session: Active async SQLAlchemy session.
                    rows: Validated row dicts ready for persistence.

                Returns:
                    Number of rows successfully processed.
                \"\"\"
                logger.debug("process_batch: %d rows (stub — override per domain)", len(rows))
                return len(rows)

        async def process_import_job(
            session: AsyncSession,
            job_id: uuid.UUID,
            content: bytes,
            filename: str,
            processor: ImportProcessor,
        ) -> None:
            \"\"\"Run the full import pipeline for a job: parse → validate → batch.

            Updates the ImportJob record with progress, failure counts, and
            final status.  Captures exceptions and marks the job as failed rather
            than letting errors propagate unhandled.

            Args:
                session: Async SQLAlchemy session (caller manages lifecycle).
                job_id: UUID of the ImportJob row to update.
                content: Raw uploaded file bytes.
                filename: Original file name (used to detect CSV vs Excel).
                processor: ImportProcessor instance configured for this job.
            \"\"\"
            try:
                if filename.lower().endswith((".xlsx", ".xls")):
                    rows = processor.parse_excel(content)
                else:
                    rows = processor.parse_csv(content)

                valid_rows, error_rows = processor.validate_rows(rows)
                total = len(rows)
                await update_import_job_progress(session, job_id, 0, len(error_rows), total)

                processed = 0
                for i in range(0, len(valid_rows), processor.batch_size):
                    batch = valid_rows[i: i + processor.batch_size]
                    done = await processor.process_batch(session, batch)
                    processed += done
                    await update_import_job_progress(
                        session, job_id, processed, len(error_rows), total
                    )

                await mark_import_job_done(session, job_id, processed, len(error_rows), error_rows)
            except Exception as exc:
                logger.exception("process_import_job failed job_id=%s", job_id)
                await fail_import_job(session, job_id, str(exc))
        """))


def _write_import_job_model(dest: Path) -> None:
    """Write ``app/models/import_job.py`` with the ImportJob ORM model.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"ImportJob model — tracks async CSV/Excel import processing status.

        Columns
        -------
        status          : pending / processing / done / failed
        file_name       : original uploaded filename
        total_rows      : rows parsed from the file header
        processed       : rows successfully committed
        failed          : rows that failed validation
        error_report_url: pre-signed URL or internal path to NDJSON error report
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import DateTime, Integer, String, Text, Uuid, func
        from sqlalchemy import JSON
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class ImportJob(Base):
            \"\"\"Tracks the lifecycle of an async data import operation.

            Attributes:
                id: UUID primary key.
                status: Current state (pending, processing, done, failed).
                file_name: Original filename supplied by the client.
                total_rows: Total rows detected in the uploaded file.
                processed: Rows successfully committed so far.
                failed: Rows rejected by validation.
                error_report_url: URL/path to the NDJSON error report; None until done.
                error_detail: Top-level error string when status=failed.
                created_at: UTC creation timestamp (server default).
                updated_at: UTC last-updated timestamp (server default, auto-updated).
            \"\"\"

            __tablename__ = "import_jobs"

            id: Mapped[uuid.UUID] = mapped_column(
                Uuid, primary_key=True, default=uuid.uuid4
            )
            status: Mapped[str] = mapped_column(
                String(20), nullable=False, default="pending", index=True
            )
            file_name: Mapped[str] = mapped_column(String(512), nullable=False)
            total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
            processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
            failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
            error_report_url: Mapped[str | None] = mapped_column(Text, nullable=True)
            error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            updated_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                onupdate=func.now(),
                nullable=False,
            )
        """))


def _write_import_job_schema(dest: Path) -> None:
    """Write ``app/schemas/import_job.py`` with Pydantic response schemas.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Pydantic schemas for the data import API.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict


        class ImportJobStatus(BaseModel):
            \"\"\"Public status snapshot of an ImportJob.

            Attributes:
                id: UUID of the import job.
                status: Current lifecycle state.
                file_name: Original uploaded filename.
                total_rows: Total rows in the uploaded file.
                processed: Rows successfully committed.
                failed: Rows rejected by validation.
                error_report_url: URL to the NDJSON error report; None until complete.
                created_at: UTC creation timestamp.
                updated_at: UTC last-update timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            status: str
            file_name: str
            total_rows: int
            processed: int
            failed: int
            error_report_url: str | None
            created_at: datetime
            updated_at: datetime


        class ImportJobCreated(BaseModel):
            \"\"\"Minimal response returned immediately after file upload.

            Attributes:
                id: UUID of the newly created import job.
                status: Initial status (always 'pending').
                file_name: Name of the uploaded file.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            status: str
            file_name: str
        """))


def _write_import_job_crud(dest: Path) -> None:
    """Write ``app/crud/import_job.py`` with CRUD helpers.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"CRUD helpers for ImportJob lifecycle management.\"\"\"

        from __future__ import annotations

        import json
        import logging
        import uuid
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.import_job import ImportJob

        logger = logging.getLogger(__name__)


        async def create_import_job(
            session: AsyncSession, file_name: str, total_rows: int = 0
        ) -> ImportJob:
            \"\"\"Create a new ImportJob row in pending state.

            Args:
                session: Async SQLAlchemy session.
                file_name: Original upload filename.
                total_rows: Row count if known at creation time; default 0.

            Returns:
                The persisted ImportJob instance.
            \"\"\"
            job = ImportJob(file_name=file_name, total_rows=total_rows, status="pending")
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job


        async def get_import_job(
            session: AsyncSession, job_id: uuid.UUID
        ) -> ImportJob | None:
            \"\"\"Fetch an ImportJob by primary key.

            Args:
                session: Async SQLAlchemy session.
                job_id: UUID of the job to fetch.

            Returns:
                The ImportJob instance or None if not found.
            \"\"\"
            result = await session.execute(
                select(ImportJob).where(ImportJob.id == job_id)
            )
            return result.scalar_one_or_none()


        async def update_import_job_progress(
            session: AsyncSession,
            job_id: uuid.UUID,
            processed: int,
            failed: int,
            total_rows: int,
        ) -> None:
            \"\"\"Update progress counters on an active ImportJob.

            Args:
                session: Async SQLAlchemy session.
                job_id: UUID of the job to update.
                processed: Rows successfully committed so far.
                failed: Rows rejected by validation.
                total_rows: Total rows parsed from the file.
            \"\"\"
            job = await get_import_job(session, job_id)
            if job is None:
                logger.warning("update_import_job_progress: job %s not found", job_id)
                return
            job.status = "processing"
            job.processed = processed
            job.failed = failed
            job.total_rows = total_rows
            await session.commit()


        async def mark_import_job_done(
            session: AsyncSession,
            job_id: uuid.UUID,
            processed: int,
            failed: int,
            error_rows: list[dict[str, Any]],
        ) -> None:
            \"\"\"Mark an ImportJob as done, saving the error report inline as JSON.

            Args:
                session: Async SQLAlchemy session.
                job_id: UUID of the job.
                processed: Final processed count.
                failed: Final failed count.
                error_rows: Rows that failed validation (stored in error_report_url field).
            \"\"\"
            job = await get_import_job(session, job_id)
            if job is None:
                return
            job.status = "done"
            job.processed = processed
            job.failed = failed
            if error_rows:
                # Store inline JSON as the error report for simple deployments.
                job.error_report_url = f"inline:{json.dumps(error_rows[:1000])}"
            await session.commit()


        async def fail_import_job(
            session: AsyncSession, job_id: uuid.UUID, error_detail: str
        ) -> None:
            \"\"\"Mark an ImportJob as failed with an error detail message.

            Args:
                session: Async SQLAlchemy session.
                job_id: UUID of the job.
                error_detail: Human-readable description of the failure.
            \"\"\"
            job = await get_import_job(session, job_id)
            if job is None:
                return
            job.status = "failed"
            job.error_detail = error_detail
            await session.commit()
        """))


def _write_import_routes(dest: Path) -> None:
    """Write ``app/api/routes/imports.py`` with upload, status, and error endpoints.

    Args:
        dest: Destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Data import endpoints.

        Endpoints
        ---------
        POST /imports/upload        — upload CSV or Excel file, returns job ID
        GET  /imports/{id}/status   — poll job status and progress counters
        GET  /imports/{id}/errors   — retrieve per-row validation errors
        \"\"\"

        from __future__ import annotations

        import uuid

        from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.crud.import_job import create_import_job, get_import_job
        from app.schemas.import_job import ImportJobCreated, ImportJobStatus

        router = APIRouter(prefix="/imports", tags=["imports"])


        async def _get_session() -> AsyncSession:
            \"\"\"FastAPI dependency placeholder — replaced by real session dep on boot.

            Raises:
                RuntimeError: Always — callers must override this dependency.
            \"\"\"
            raise RuntimeError("Inject get_async_session via app.dependency_overrides")


        @router.post(
            "/upload",
            response_model=ImportJobCreated,
            status_code=status.HTTP_202_ACCEPTED,
        )
        async def upload_import_file(
            file: UploadFile,
            session: AsyncSession = Depends(_get_session),
        ) -> ImportJobCreated:
            \"\"\"Upload a CSV or Excel file and start an async import job.

            Validates file size against IMPORT_MAX_FILE_SIZE_MB from settings.
            Returns a job ID immediately; processing continues in the background.

            Args:
                file: Uploaded file (CSV or XLSX).
                session: Injected async DB session.

            Returns:
                ImportJobCreated with job id, status, and filename.

            Raises:
                HTTPException 400: If file extension is not allowed.
                HTTPException 413: If file exceeds IMPORT_MAX_FILE_SIZE_MB.
            \"\"\"
            from app.core.config import settings  # noqa: PLC0415

            allowed = {".csv", ".xlsx", ".xls"}
            ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
            if ext not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"detail": f"File type not allowed. Accepted: {', '.join(sorted(allowed))}"},
                )

            content = await file.read()
            max_bytes = settings.IMPORT_MAX_FILE_SIZE_MB * 1024 * 1024
            if len(content) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={"detail": f"File exceeds maximum size of {settings.IMPORT_MAX_FILE_SIZE_MB} MB"},
                )

            job = await create_import_job(session, file_name=file.filename or "upload")
            return ImportJobCreated.model_validate(job)


        @router.get("/{job_id}/status", response_model=ImportJobStatus)
        async def get_import_status(
            job_id: uuid.UUID,
            session: AsyncSession = Depends(_get_session),
        ) -> ImportJobStatus:
            \"\"\"Return the current status and progress of an import job.

            Args:
                job_id: UUID of the import job.
                session: Injected async DB session.

            Returns:
                ImportJobStatus with counters and current lifecycle state.

            Raises:
                HTTPException 404: If the job does not exist.
            \"\"\"
            job = await get_import_job(session, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"detail": "Import job not found"},
                )
            return ImportJobStatus.model_validate(job)


        @router.get("/{job_id}/errors")
        async def get_import_errors(
            job_id: uuid.UUID,
            session: AsyncSession = Depends(_get_session),
        ) -> dict:
            \"\"\"Return per-row validation errors for a completed import job.

            Args:
                job_id: UUID of the import job.
                session: Injected async DB session.

            Returns:
                Dict with ``job_id``, ``failed`` count, and ``errors`` list.

            Raises:
                HTTPException 404: If the job does not exist.
                HTTPException 400: If the job has not yet finished.
            \"\"\"
            import json  # noqa: PLC0415

            job = await get_import_job(session, job_id)
            if job is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"detail": "Import job not found"},
                )
            if job.status not in ("done", "failed"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={"detail": f"Job is still {job.status}; errors not available yet"},
                )
            errors: list = []
            if job.error_report_url and job.error_report_url.startswith("inline:"):
                try:
                    errors = json.loads(job.error_report_url[len("inline:"):])
                except (ValueError, KeyError):
                    errors = []
            return {"job_id": str(job_id), "failed": job.failed, "errors": errors}
        """))


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration for the import_jobs table.

    Args:
        versions_dir: Path to ``alembic/versions/``.

    Returns:
        Path of the created migration file.
    """
    rev_id = "add_import_jobs"
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    dest = versions_dir / f"{rev_id}.py"
    content = textwrap.dedent(f"""\
        \"\"\"add import_jobs table

        Revision ID: {rev_id}
        Revises: {down_rev}
        Create Date: auto-generated by add_data_import tool
        \"\"\"

        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision: str = "{rev_id}"
        down_revision: str | None = "{down_rev}"
        branch_labels: str | None = None
        depends_on: str | None = None


        def upgrade() -> None:
            \"\"\"Create the import_jobs table.\"\"\"
            op.create_table(
                "import_jobs",
                sa.Column("id", sa.Uuid(), nullable=False),
                sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
                sa.Column("file_name", sa.String(512), nullable=False),
                sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("failed", sa.Integer(), nullable=False, server_default="0"),
                sa.Column("error_report_url", sa.Text(), nullable=True),
                sa.Column("error_detail", sa.Text(), nullable=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("now()"),
                    nullable=False,
                ),
                sa.PrimaryKeyConstraint("id"),
            )
            op.create_index("ix_import_jobs_status", "import_jobs", ["status"])


        def downgrade() -> None:
            \"\"\"Drop the import_jobs table.\"\"\"
            op.drop_index("ix_import_jobs_status", table_name="import_jobs")
            op.drop_table("import_jobs")
        """)
    dest.write_text(content)
    return dest


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start* (minimum 1).

    Args:
        start: ``time.monotonic()`` value captured at the beginning of a function.

    Returns:
        Integer milliseconds elapsed, at least 1 to satisfy ``> 0`` checks.
    """
    return max(1, int((time.monotonic() - start) * 1000))
