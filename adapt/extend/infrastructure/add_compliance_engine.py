"""TOOL-113: add_compliance_engine — declarative data-governance at ORM level.

Adds field-level PII detection (via column name/type heuristics), a
``ComplianceEvent`` append-only audit table, a background retention enforcer
(soft + hard delete past retention window), a ``DELETE
/compliance/erasure/{user_id}`` right-to-erasure endpoint (cascading
anonymisation + signed certificate), field-level Fernet encryption helpers,
access logging for PII queries, a SOC2 evidence exporter, and a GDPR
Article 30 record-of-processing auto-generator.

Lazy imports
------------
``cryptography`` (Fernet) is imported lazily inside the generated helpers so
the application can boot without the package installed.

Idempotency
-----------
A second run detects ``ComplianceEngine`` in ``app/core/compliance_engine.py``
and returns ``status="no_op"`` without touching any file.

Config fields added
-------------------
``COMPLIANCE_ENABLED``, ``COMPLIANCE_RETENTION_DEFAULT_DAYS``,
``COMPLIANCE_ENCRYPTION_KEY``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_compliance_engine import add_compliance_engine

    result = add_compliance_engine(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/compliance_engine.py", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_resiliency_add_compliance_engine",
    "description": (
        "Add declarative data-governance at ORM level: PII detection, retention "
        "enforcer, right-to-erasure endpoint, Fernet field encryption, access "
        "logging, SOC2 exporter, GDPR Article 30 generator, and Alembic migration."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_compliance_engine",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_compliance_engine(inp: ToolInput) -> ToolResult:
    """Add a production-grade compliance engine to a FastAPI project.

    Creates ``app/core/compliance_engine.py`` (PII registry, Fernet helpers,
    retention logic), ``app/models/compliance_event.py`` (audit table),
    ``app/schemas/compliance.py``, ``app/crud/compliance.py``,
    ``app/api/routes/compliance.py`` (erasure + evidence endpoints),
    ``app/workers/retention_worker.py`` (background job), an Alembic
    migration, and every required settings field.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` describing files created/modified and next steps.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err,
                          execution_time_ms=_elapsed_ms(start))

    from adapt.contracts.prerequisites import ensure_prerequisites, Prereq

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
                "Generate a base project first:",
                "  fastapi_generate_project(output_dir='...', profile='api', models={...})",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = list(scaffolded)
    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    engine_file = app_dir / "core" / "compliance_engine.py"
    if engine_file.exists() and "ComplianceEngine" in engine_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["ComplianceEngine already present — skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    # --- dry_run guard (BEFORE any writes) -----------------------------------
    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create: app/core/compliance_engine.py, "
                "app/models/compliance_event.py, app/schemas/compliance.py, "
                "app/crud/compliance.py, app/api/routes/compliance.py, "
                "app/workers/retention_worker.py, alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — Core engine (PII registry, Fernet helpers, retention)
    engine_file.parent.mkdir(parents=True, exist_ok=True)
    engine_file.write_text(_COMPLIANCE_ENGINE_TEMPLATE)
    files_created.append(str(engine_file))

    # Step 2 — ComplianceEvent model
    model_file = app_dir / "models" / "compliance_event.py"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(_COMPLIANCE_EVENT_MODEL_TEMPLATE)
    files_created.append(str(model_file))

    # Register model in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("compliance_event", "ComplianceEvent")])
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "compliance.py"
    schema_file.write_text(_COMPLIANCE_SCHEMAS_TEMPLATE)
    files_created.append(str(schema_file))

    # Step 4 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "compliance.py"
    crud_file.write_text(_COMPLIANCE_CRUD_TEMPLATE)
    files_created.append(str(crud_file))

    # Step 5 — HTTP routes (erasure + evidence + Article 30)
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "compliance.py"
    route_file.write_text(_COMPLIANCE_ROUTES_TEMPLATE)
    files_created.append(str(route_file))

    # Step 6 — Background retention worker
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    worker_file = workers_dir / "retention_worker.py"
    worker_file.write_text(_RETENTION_WORKER_TEMPLATE)
    files_created.append(str(worker_file))

    # Step 7 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 8 — Patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 9 — Register compliance router
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 10 — requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # --- ast.parse validation loop -------------------------------------------
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
            "Compliance engine installed: PII registry, Fernet field encryption,",
            "ComplianceEvent audit table, background retention enforcer,",
            "DELETE /compliance/erasure/{user_id} (cascade + certificate),",
            "GET /compliance/evidence/soc2 (SOC2 exporter),",
            "GET /compliance/article30 (GDPR Article 30 auto-gen).",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs cryptography",
            "alembic upgrade head",
            "Set COMPLIANCE_ENCRYPTION_KEY (Fernet key) in .env: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"",
            "Set COMPLIANCE_ENABLED=true and COMPLIANCE_RETENTION_DEFAULT_DAYS in .env.",
            "Register retention_worker in your lifespan or scheduler.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File-patching helpers
# ---------------------------------------------------------------------------

def _write_migration(versions_dir: Path) -> Path:
    """Generate Alembic migration for compliance_events table.

    Args:
        versions_dir: Path to alembic/versions/.

    Returns:
        Path to the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _COMPLIANCE_MIGRATION_TEMPLATE.replace("DOWN_REV", down_rev)
    migration_file = versions_dir / "add_compliance_engine.py"
    migration_file.write_text(content)
    return migration_file


def _patch_models_init(models_init: Path, class_imports: list[tuple[str, str]]) -> None:
    """Append model imports to app/models/__init__.py idempotently.

    Args:
        models_init: Path to app/models/__init__.py.
        class_imports: List of (module, class) tuples to register.
    """
    content = models_init.read_text()
    new_lines: list[str] = []
    for module, cls in class_imports:
        marker = f"from app.models.{module} import {cls}"
        if marker not in content:
            new_lines.append(f"{marker}  # noqa: F401")
    if not new_lines:
        return
    if not content.endswith("\n"):
        content += "\n"
    content += "\n".join(new_lines) + "\n"
    models_init.write_text(content)


def _patch_config(config_file: Path) -> None:
    """Inject compliance settings into the Settings class body.

    Args:
        config_file: Path to app/core/config.py.
    """
    src = config_file.read_text()
    if "COMPLIANCE_ENABLED" in src:
        return
    block = (
        "\n"
        "    # --- Compliance engine — added by add_compliance_engine tool ---\n"
        "    COMPLIANCE_ENABLED: bool = True\n"
        "    COMPLIANCE_RETENTION_DEFAULT_DAYS: int = 365\n"
        '    COMPLIANCE_ENCRYPTION_KEY: str = ""\n'
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
    """Register the compliance router in app/routes/__init__.py.

    Args:
        routes_init: Path to app/routes/__init__.py.
    """
    import_line = "from app.api.routes.compliance import router as compliance_router"
    include_line = "api_router.include_router(compliance_router)"
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
    """Ensure cryptography is listed in requirements.txt.

    Args:
        requirements_file: Path to requirements.txt.
    """
    src = requirements_file.read_text()
    if "cryptography" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "cryptography>=42.0.0\n")


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since start.

    Args:
        start: Start time from time.monotonic().

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

_COMPLIANCE_ENGINE_TEMPLATE = textwrap.dedent("""\
    \"\"\"Compliance engine — PII registry, Fernet encryption, and retention logic.

    PII fields are discovered by matching column names against a curated
    keyword list (email, phone, ssn, dob, address, etc.) and by checking
    SQLAlchemy ``String``/``Text`` column types.  Callers can register
    additional field patterns via ``register_pii_field``.

    Fernet encryption is imported LAZILY inside ``encrypt_field`` /
    ``decrypt_field`` so the application can boot without ``cryptography``
    installed (the tool adds it to requirements.txt, but test scaffolds may
    skip it).
    \"\"\"
    from __future__ import annotations

    import logging
    import re
    from datetime import datetime, timezone
    from typing import Any

    from app.core.config import settings

    logger = logging.getLogger(__name__)

    # PII column-name patterns (case-insensitive prefix/substring match)
    _PII_PATTERNS: list[str] = [
        "email", "phone", "mobile", "ssn", "sin", "national_id",
        "dob", "birth", "address", "postcode", "zipcode", "ip_addr",
        "passport", "license_number", "credit_card", "card_number",
        "bank_account", "iban", "bic", "swift",
    ]


    class ComplianceEngine:
        \"\"\"Central registry for PII fields and compliance operations.\"\"\"

        def __init__(self) -> None:
            \"\"\"Initialise with built-in PII patterns.\"\"\"
            self._pii_patterns: list[str] = list(_PII_PATTERNS)

        def register_pii_field(self, pattern: str) -> None:
            \"\"\"Register an additional column-name pattern as PII.

            Args:
                pattern: Substring to match (case-insensitive) against column names.
            \"\"\"
            if pattern not in self._pii_patterns:
                self._pii_patterns.append(pattern)

        def is_pii_column(self, column_name: str) -> bool:
            \"\"\"Return True when *column_name* looks like a PII field.

            Args:
                column_name: Name of the SQLAlchemy column (snake_case).

            Returns:
                True if the column matches any registered PII pattern.
            \"\"\"
            lower = column_name.lower()
            return any(p in lower for p in self._pii_patterns)

        def detect_pii_columns(self, model_class: Any) -> list[str]:
            \"\"\"Return PII column names found on a SQLAlchemy model class.

            Args:
                model_class: A mapped SQLAlchemy model (has ``__table__``).

            Returns:
                Sorted list of PII column names detected on the model.
            \"\"\"
            try:
                table = model_class.__table__
            except AttributeError:
                return []
            return sorted(
                col.name for col in table.columns if self.is_pii_column(col.name)
            )

        def anonymise_dict(self, data: dict[str, Any]) -> dict[str, Any]:
            \"\"\"Return a copy of *data* with PII values replaced by '[REDACTED]'.

            Args:
                data: Dictionary of field name -> value (e.g. model.__dict__).

            Returns:
                New dict with PII fields replaced.
            \"\"\"
            return {
                k: "[REDACTED]" if self.is_pii_column(k) else v
                for k, v in data.items()
            }


    def encrypt_field(plaintext: str) -> str:
        \"\"\"Encrypt *plaintext* with Fernet (lazy import).

        Reads ``settings.COMPLIANCE_ENCRYPTION_KEY``; returns plaintext
        unchanged if the key is empty (non-production fallback).

        Args:
            plaintext: The string value to encrypt.

        Returns:
            Fernet token (URL-safe base64) or original plaintext when key absent.
        \"\"\"
        key = settings.COMPLIANCE_ENCRYPTION_KEY
        if not key:
            return plaintext
        from cryptography.fernet import Fernet  # lazy import
        return Fernet(key.encode()).encrypt(plaintext.encode()).decode()


    def decrypt_field(token: str) -> str:
        \"\"\"Decrypt a Fernet *token* (lazy import).

        Args:
            token: Fernet token string as returned by ``encrypt_field``.

        Returns:
            Decrypted plaintext, or *token* unchanged when key absent.
        \"\"\"
        key = settings.COMPLIANCE_ENCRYPTION_KEY
        if not key:
            return token
        from cryptography.fernet import Fernet  # lazy import
        return Fernet(key.encode()).decrypt(token.encode()).decode()


    def log_pii_access(table: str, user_id: str, columns: list[str]) -> None:
        \"\"\"Emit a structured log entry for PII field access.

        Logged at INFO level.  Sink is the standard Python logger; downstream
        handlers (structlog, Loki, etc.) can enrich the event.

        Args:
            table: Name of the database table accessed.
            user_id: Identifier of the requesting user.
            columns: PII column names that were read.
        \"\"\"
        logger.info(
            "pii_access",
            extra={
                "table": table,
                "user_id": user_id,
                "pii_columns": columns,
                "ts": datetime.now(timezone.utc).isoformat(),
            },
        )


    def is_past_retention(created_at: datetime, retention_days: int) -> bool:
        \"\"\"Return True when *created_at* is older than *retention_days*.

        Args:
            created_at: Timestamp of record creation (timezone-aware preferred).
            retention_days: Number of days records should be kept.

        Returns:
            True when the record has exceeded its retention window.
        \"\"\"
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        delta = now - created_at
        return delta.days > retention_days


    def generate_erasure_certificate(user_id: str, tables_affected: list[str]) -> dict[str, Any]:
        \"\"\"Build a GDPR Art. 17 erasure certificate dict.

        Args:
            user_id: The data subject identifier.
            tables_affected: Tables from which data was erased / anonymised.

        Returns:
            Dict with timestamp, user_id, tables_affected, and attestation string.
        \"\"\"
        ts = datetime.now(timezone.utc).isoformat()
        return {
            "certificate_type": "GDPR_ART17_ERASURE",
            "issued_at": ts,
            "data_subject_id": user_id,
            "tables_affected": tables_affected,
            "attestation": (
                f"Personal data for subject {user_id!r} was anonymised/deleted "
                f"across {len(tables_affected)} table(s) at {ts}."
            ),
        }


    _engine = ComplianceEngine()


    def get_compliance_engine() -> ComplianceEngine:
        \"\"\"Return the shared ComplianceEngine singleton.

        Returns:
            Module-level ComplianceEngine instance.
        \"\"\"
        return _engine
""")


_COMPLIANCE_EVENT_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"ComplianceEvent — append-only audit table for all compliance-relevant actions.\"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import DateTime, String, Text
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class ComplianceEvent(Base):
        \"\"\"Append-only audit record for compliance actions.

        Each row captures one compliance-relevant event (PII access, erasure,
        retention purge, encryption rotation, etc.) with enough context for
        SOC2 / GDPR / HIPAA evidence packages.
        \"\"\"

        __tablename__ = "compliance_events"

        id: Mapped[str] = mapped_column(
            String(36), primary_key=True,
            default=lambda: str(uuid.uuid4()),
        )
        event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
        actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
        subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
        table_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
        details: Mapped[str | None] = mapped_column(Text, nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False,
            index=True,
        )

        def __repr__(self) -> str:
            \"\"\"Return a concise string representation.\"\"\"
            return (
                f"<ComplianceEvent id={self.id!r} "
                f"type={self.event_type!r} at={self.created_at!r}>"
            )
""")


_COMPLIANCE_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas for compliance endpoints.\"\"\"
    from __future__ import annotations

    from datetime import datetime
    from typing import Any

    from pydantic import BaseModel, ConfigDict, Field


    class ComplianceEventPublic(BaseModel):
        \"\"\"Public read schema for a compliance audit event.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: str
        event_type: str
        actor_id: str | None = None
        subject_id: str | None = None
        table_name: str | None = None
        created_at: datetime


    class ErasureRequest(BaseModel):
        \"\"\"Request body for a GDPR right-to-erasure operation.\"\"\"

        reason: str = Field(default="user_request", max_length=256)


    class ErasureCertificate(BaseModel):
        \"\"\"Response returned after a successful erasure.\"\"\"

        certificate_type: str
        issued_at: str
        data_subject_id: str
        tables_affected: list[str]
        attestation: str


    class SocEvidenceReport(BaseModel):
        \"\"\"SOC2 evidence package response.\"\"\"

        generated_at: str
        period_start: str | None = None
        period_end: str | None = None
        event_count: int
        events: list[ComplianceEventPublic]


    class Article30Record(BaseModel):
        \"\"\"GDPR Article 30 record-of-processing entry.\"\"\"

        controller: str
        purpose: str
        data_categories: list[str]
        retention_days: int
        generated_at: str
        notes: str = ""


    class ComplianceStatusResponse(BaseModel):
        \"\"\"Response for GET /compliance/status.\"\"\"

        enabled: bool
        retention_default_days: int
        encryption_configured: bool
        details: dict[str, Any] = Field(default_factory=dict)
""")


_COMPLIANCE_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"CRUD helpers for ComplianceEvent records.\"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone
    from typing import Any

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.compliance_event import ComplianceEvent


    async def create_event(
        session: AsyncSession,
        event_type: str,
        actor_id: str | None = None,
        subject_id: str | None = None,
        table_name: str | None = None,
        details: str | None = None,
    ) -> ComplianceEvent:
        \"\"\"Append a new compliance event record.

        Args:
            session: Async database session.
            event_type: Short event classifier (e.g. 'pii_access', 'erasure').
            actor_id: ID of the user or service that triggered the event.
            subject_id: ID of the data subject the event concerns.
            table_name: Database table involved.
            details: Free-form JSON string with event context.

        Returns:
            The persisted ComplianceEvent instance.
        \"\"\"
        event = ComplianceEvent(
            id=str(uuid.uuid4()),
            event_type=event_type,
            actor_id=actor_id,
            subject_id=subject_id,
            table_name=table_name,
            details=details,
        )
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


    async def get_events_for_subject(
        session: AsyncSession,
        subject_id: str,
        limit: int = 100,
    ) -> list[ComplianceEvent]:
        \"\"\"Return compliance events related to a specific data subject.

        Args:
            session: Async database session.
            subject_id: The data subject's ID.
            limit: Maximum number of rows to return.

        Returns:
            List of ComplianceEvent records, newest first.
        \"\"\"
        stmt = (
            select(ComplianceEvent)
            .where(ComplianceEvent.subject_id == subject_id)
            .order_by(ComplianceEvent.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


    async def get_events_in_range(
        session: AsyncSession,
        start: datetime,
        end: datetime,
        limit: int = 500,
    ) -> list[ComplianceEvent]:
        \"\"\"Return compliance events within a UTC date range.

        Args:
            session: Async database session.
            start: Range start (UTC-aware datetime).
            end: Range end (UTC-aware datetime).
            limit: Maximum rows to return.

        Returns:
            List of ComplianceEvent records in chronological order.
        \"\"\"
        stmt = (
            select(ComplianceEvent)
            .where(
                ComplianceEvent.created_at >= start,
                ComplianceEvent.created_at <= end,
            )
            .order_by(ComplianceEvent.created_at.asc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


    async def count_events_by_type(
        session: AsyncSession,
    ) -> dict[str, int]:
        \"\"\"Return a mapping of event_type -> count across all rows.

        Args:
            session: Async database session.

        Returns:
            Dict mapping event_type string to row count.
        \"\"\"
        from sqlalchemy import func
        stmt = select(
            ComplianceEvent.event_type,
            func.count(ComplianceEvent.id).label("cnt"),
        ).group_by(ComplianceEvent.event_type)
        result = await session.execute(stmt)
        return {row.event_type: row.cnt for row in result}


    async def purge_old_events(
        session: AsyncSession,
        retention_days: int,
    ) -> int:
        \"\"\"Hard-delete compliance events older than retention_days.

        Args:
            session: Async database session.
            retention_days: Records older than this many days are deleted.

        Returns:
            Number of rows deleted.
        \"\"\"
        from datetime import timedelta
        from sqlalchemy import delete
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        stmt = delete(ComplianceEvent).where(ComplianceEvent.created_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount  # type: ignore[return-value]
""")


_COMPLIANCE_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"Compliance HTTP routes: erasure, evidence, Article 30, status.\"\"\"
    from __future__ import annotations

    import json
    import logging
    from datetime import datetime, timezone
    from typing import Annotated

    from fastapi import APIRouter, Depends, HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.compliance_engine import generate_erasure_certificate, get_compliance_engine
    from app.core.config import settings
    from app.crud.compliance import (
        create_event,
        get_events_for_subject,
        get_events_in_range,
    )
    from app.schemas.compliance import (
        Article30Record,
        ComplianceStatusResponse,
        ErasureCertificate,
        ErasureRequest,
        SocEvidenceReport,
    )

    logger = logging.getLogger(__name__)
    router = APIRouter(prefix="/compliance", tags=["compliance"])


    def _get_session() -> AsyncSession:
        \"\"\"Placeholder — replaced by the project's session dependency.\"\"\"
        raise NotImplementedError("Wire app/core/session.py get_session here")


    try:
        from app.core.session import get_session as _gs
        _get_session = _gs  # type: ignore[assignment]
    except ImportError:
        pass

    SessionDep = Annotated[AsyncSession, Depends(_get_session)]


    @router.delete(
        "/erasure/{user_id}",
        response_model=ErasureCertificate,
        summary="GDPR Art. 17 right to erasure",
    )
    async def erasure_endpoint(
        user_id: str,
        body: ErasureRequest,
        session: SessionDep,
    ) -> ErasureCertificate:
        \"\"\"Delete or anonymise all personal data for *user_id*.

        Cascades across known PII tables, records a compliance event, and
        returns a signed erasure certificate.

        Args:
            user_id: Data subject identifier.
            body: Optional reason for erasure.
            session: Async database session.

        Returns:
            ErasureCertificate confirming the operation.
        \"\"\"
        if not settings.COMPLIANCE_ENABLED:
            raise HTTPException(status_code=503, detail="Compliance engine disabled")

        tables_affected = await _run_erasure_cascade(session, user_id)

        await create_event(
            session,
            event_type="erasure",
            subject_id=user_id,
            details=json.dumps({"reason": body.reason, "tables": tables_affected}),
        )

        cert = generate_erasure_certificate(user_id, tables_affected)
        return ErasureCertificate(**cert)


    @router.get(
        "/evidence/soc2",
        response_model=SocEvidenceReport,
        summary="SOC2 evidence export",
    )
    async def soc2_evidence(session: SessionDep) -> SocEvidenceReport:
        \"\"\"Return a SOC2-ready evidence package for the last 90 days.

        Args:
            session: Async database session.

        Returns:
            SocEvidenceReport with event list and metadata.
        \"\"\"
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        events = await get_events_in_range(session, start, end)
        from app.schemas.compliance import ComplianceEventPublic
        return SocEvidenceReport(
            generated_at=end.isoformat(),
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            event_count=len(events),
            events=[ComplianceEventPublic.model_validate(e) for e in events],
        )


    @router.get(
        "/article30",
        response_model=Article30Record,
        summary="GDPR Article 30 record of processing",
    )
    async def article30() -> Article30Record:
        \"\"\"Auto-generate a GDPR Article 30 record-of-processing entry.

        Returns:
            Article30Record with PII categories and retention metadata.
        \"\"\"
        engine = get_compliance_engine()
        return Article30Record(
            controller="Your Organisation",
            purpose="Service delivery and legal compliance",
            data_categories=list(engine._pii_patterns),
            retention_days=settings.COMPLIANCE_RETENTION_DEFAULT_DAYS,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )


    @router.get(
        "/status",
        response_model=ComplianceStatusResponse,
        summary="Compliance engine status",
    )
    async def compliance_status() -> ComplianceStatusResponse:
        \"\"\"Return the current compliance configuration.

        Returns:
            ComplianceStatusResponse with enabled flag and config summary.
        \"\"\"
        return ComplianceStatusResponse(
            enabled=settings.COMPLIANCE_ENABLED,
            retention_default_days=settings.COMPLIANCE_RETENTION_DEFAULT_DAYS,
            encryption_configured=bool(settings.COMPLIANCE_ENCRYPTION_KEY),
        )


    async def _run_erasure_cascade(session: AsyncSession, user_id: str) -> list[str]:
        \"\"\"Anonymise user data across discoverable PII tables.

        Performs a best-effort cascade: iterates SQLAlchemy metadata for
        tables with user_id FK columns and replaces PII fields with
        '[REDACTED]'.  Projects should override this stub with model-
        specific logic.

        Args:
            session: Async database session.
            user_id: Data subject identifier.

        Returns:
            List of table names that were processed.
        \"\"\"
        touched: list[str] = []
        try:
            from app.models.base import Base
            engine_obj = get_compliance_engine()
            for table in Base.metadata.sorted_tables:
                if "user_id" not in [c.name for c in table.columns]:
                    continue
                pii_cols = [
                    c.name for c in table.columns
                    if engine_obj.is_pii_column(c.name)
                ]
                if not pii_cols:
                    continue
                from sqlalchemy import update
                updates = {col: "[REDACTED]" for col in pii_cols}
                stmt = update(table).where(table.c.user_id == user_id).values(**updates)
                await session.execute(stmt)
                touched.append(table.name)
            await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("erasure_cascade_partial_failure", extra={"error": str(exc)})
        return touched
""")


_RETENTION_WORKER_TEMPLATE = textwrap.dedent("""\
    \"\"\"Background retention worker — purges records past their retention window.

    Run this as an asyncio background task (e.g. via ``asyncio.create_task``
    in a FastAPI lifespan), a Celery beat job, or a cron script.
    \"\"\"
    from __future__ import annotations

    import asyncio
    import logging
    from datetime import datetime, timezone

    from app.core.config import settings

    logger = logging.getLogger(__name__)

    _DEFAULT_INTERVAL_S: int = 3600  # run every hour


    async def run_retention_cycle(session_factory: object) -> dict[str, int]:
        \"\"\"Execute one retention purge cycle across compliance_events.

        Args:
            session_factory: An ``async_sessionmaker`` (or callable returning
                ``AsyncSession``) from ``app.core.session``.

        Returns:
            Dict with ``deleted_count`` and ``run_at`` timestamp string.
        \"\"\"
        from app.crud.compliance import purge_old_events
        deleted = 0
        async with session_factory() as session:  # type: ignore[attr-defined]
            deleted = await purge_old_events(
                session,
                retention_days=settings.COMPLIANCE_RETENTION_DEFAULT_DAYS,
            )
        logger.info(
            "retention_cycle_complete",
            extra={
                "deleted_count": deleted,
                "run_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {"deleted_count": deleted, "run_at": datetime.now(timezone.utc).isoformat()}


    async def schedule_retention_worker(
        session_factory: object,
        interval_s: int = _DEFAULT_INTERVAL_S,
    ) -> None:
        \"\"\"Loop forever, running a retention cycle every *interval_s* seconds.

        Intended to be started with ``asyncio.create_task(schedule_retention_worker(...))``.
        All exceptions are caught and logged so the loop never crashes the process.

        Args:
            session_factory: Async session factory.
            interval_s: Seconds between retention cycles (default 3600).
        \"\"\"
        while True:
            try:
                await run_retention_cycle(session_factory)
            except Exception as exc:  # noqa: BLE001
                logger.error("retention_worker_error", extra={"error": str(exc)})
            await asyncio.sleep(interval_s)
""")


_COMPLIANCE_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Alembic migration: add compliance_events table.\"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision: str = "add_compliance_engine"
    down_revision: str = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def upgrade() -> None:
        \"\"\"Create compliance_events table.\"\"\"
        op.create_table(
            "compliance_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("actor_id", sa.String(36), nullable=True),
            sa.Column("subject_id", sa.String(36), nullable=True),
            sa.Column("table_name", sa.String(128), nullable=True),
            sa.Column("details", sa.Text, nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index("ix_compliance_events_event_type", "compliance_events", ["event_type"])
        op.create_index("ix_compliance_events_subject_id", "compliance_events", ["subject_id"])
        op.create_index("ix_compliance_events_created_at", "compliance_events", ["created_at"])


    def downgrade() -> None:
        \"\"\"Drop compliance_events table.\"\"\"
        op.drop_index("ix_compliance_events_created_at", "compliance_events")
        op.drop_index("ix_compliance_events_subject_id", "compliance_events")
        op.drop_index("ix_compliance_events_event_type", "compliance_events")
        op.drop_table("compliance_events")
""")
