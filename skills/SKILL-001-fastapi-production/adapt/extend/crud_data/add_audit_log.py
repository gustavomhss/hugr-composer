"""TOOL-005: add_audit_log — add a tamper-evident audit log to a FastAPI/SQLAlchemy project.

Generates an ``AuditLog`` model with JSONB diff columns, a SHA-256 hash-chain
linking each entry to the previous one, SQLAlchemy ``Session.before_flush`` event
listeners for automatic capture of every INSERT/UPDATE/DELETE on tracked models, a
``CurrentAuditor`` dependency, a read-only query API (``GET /audit-logs/``), a
hash-chain verifier endpoint (``POST /audit-logs/verify``), a PostgreSQL immutability
trigger that rejects any UPDATE/DELETE on the audit table, and an Alembic migration
with monthly partitioning.

The tool is idempotent: a second run detects the ``AuditLog`` fingerprint and
returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.crud_data.add_audit_log import add_audit_log

    result = add_audit_log(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # [".../app/models/audit_log.py", ...]
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

def add_audit_log(inp: ToolInput) -> ToolResult:
    """Add compliance-grade audit logging to a FastAPI project.

    Creates the AuditLog model, context vars, event listeners, schemas, CRUD,
    routes, and an Alembic migration with immutability trigger and monthly
    partitioning.

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
        return ToolResult(status="error", error=err)

    app_dir = project / "app"

    # --- Pre-flight: is audit log already installed? ----------------------
    audit_model = app_dir / "models" / "audit_log.py"
    if audit_model.exists() and "AuditLog" in audit_model.read_text():
        return ToolResult(
            status="no_op",
            notes=["AuditLog model already present — audit logging is already enabled, skipped."],
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
                f"[dry_run] Would add AuditLog for models: {', '.join(model_names)}",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # --- Step 1: AuditLog model ------------------------------------------
    _write_audit_model(audit_model)
    files_created.append(str(audit_model))

    # Register AuditLog in app/models/__init__.py for metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("audit_log", "AuditLog")],
    )

    # --- Step 2: Audit context (contextvars for user_id + request meta) --
    context_file = app_dir / "core" / "audit_context.py"
    _write_audit_context(context_file)
    files_created.append(str(context_file))

    # --- Step 3: Event listeners (before_flush capture) ------------------
    listeners_file = app_dir / "core" / "audit_listeners.py"
    _write_audit_listeners(listeners_file, model_pairs)
    files_created.append(str(listeners_file))

    # --- Step 4: Hash-chain verifier -------------------------------------
    verifier_file = app_dir / "core" / "audit_verifier.py"
    _write_audit_verifier(verifier_file)
    files_created.append(str(verifier_file))

    # --- Step 5: Schemas (AuditLogFilter, AuditLogPage, VerifyRequest) ---
    schema_file = app_dir / "schemas" / "audit_log.py"
    _write_audit_schemas(schema_file)
    files_created.append(str(schema_file))

    # --- Step 6: Read-only CRUD ------------------------------------------
    crud_file = app_dir / "crud" / "audit_log.py"
    _write_audit_crud(crud_file)
    files_created.append(str(crud_file))

    # --- Step 7: Auditor dependency (CurrentAuditor) ---------------------
    deps_file = app_dir / "api" / "deps.py"
    if deps_file.exists():
        _patch_deps(deps_file)
        files_modified.append(str(deps_file))

    # --- Step 8: Audit log routes ----------------------------------------
    routes_file = app_dir / "api" / "routes" / "audit_logs.py"
    _write_audit_routes(routes_file)
    files_created.append(str(routes_file))

    # --- Step 9: Register listeners + middleware in main.py --------------
    main_file = app_dir / "main.py"
    if main_file.exists():
        _patch_main(main_file)
        files_modified.append(str(main_file))

    # --- Step 10: Alembic migration with partition + trigger -------------
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_migration(versions_dir)
        files_created.append(str(migration_file))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Audit logging enabled for: {', '.join(model_names)}",
            "SHA-256 hash chain links every entry to the previous one.",
            "PostgreSQL immutability trigger rejects any UPDATE/DELETE on audit_logs.",
            "Monthly partitioning via PARTITION BY RANGE (created_at).",
            "Access gated behind CurrentAuditor (role=auditor or is_superuser).",
        ],
        next_steps=[
            "alembic upgrade head",
            "Register AuditContextMiddleware in app/main.py to capture request IP/user-agent.",
            "Restart the application so the before_flush listener is active.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently."""
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


def _discover_models(app_dir: Path) -> list[tuple[str, str]]:
    """Return (snake_stem, PascalCase) pairs found in ``app/models/``, excluding system models.

    Only includes models where:
    1. The file contains a class named ``{pascal}`` inheriting from ``Base``.
    2. A matching route file ``app/api/routes/{stem}.py`` exists.

    Args:
        app_dir: The ``app/`` package directory.

    Returns:
        Sorted list of ``(snake_stem, PascalName)`` tuples.
    """
    import ast as _ast

    models_dir = app_dir / "models"
    routes_dir = app_dir / "api" / "routes"
    skip = {"base", "user", "mixins", "audit_log", "__init__"}
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
        # Derive PascalCase class name: item -> Item, order_item -> OrderItem
        pascal = "".join(w.capitalize() for w in stem.split("_"))
        try:
            tree = _ast.parse(f.read_text())
        except SyntaxError:
            continue
        base_subclasses = [
            n.name for n in _ast.walk(tree)
            if isinstance(n, _ast.ClassDef)
            and any(
                (isinstance(b, _ast.Name) and b.id == "Base")
                or (isinstance(b, _ast.Attribute) and b.attr == "Base")
                for b in n.bases
            )
        ]
        if pascal in base_subclasses:
            pairs.append((stem, pascal))
    return pairs


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
# ---------------------------------------------------------------------------

def _write_audit_model(dest: Path) -> None:
    """Write ``app/models/audit_log.py`` with the AuditLog class.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Append-only AuditLog model with SHA-256 hash chain for tamper detection.

        Invariants enforced at DB level:
        - No UPDATE or DELETE (PostgreSQL trigger trg_audit_log_immutable)
        - created_at has server default (cannot be forged by application)
        - entry_hash is SHA-256 of row content chained to the previous entry
        \"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from sqlalchemy import (
            CheckConstraint,
            DateTime,
            Index,
            String,
            Uuid,
            func,
        )
        from sqlalchemy import JSON
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class AuditLog(Base):
            \"\"\"Immutable audit log entry.

            Attributes:
                id: UUID primary key.
                entity_type: Lowercase model class name (e.g. 'item').
                entity_id: String representation of the entity primary key.
                action: One of create/update/delete/soft_delete/restore/read.
                user_id: UUID of the acting user, nullable.
                auth_method: Authentication method used (password/api_key/oauth2/mfa), nullable.
                before_values: JSONB diff of changed fields before the operation.
                after_values: JSONB diff of changed fields after the operation.
                ip_address: Client IP from the request (INET type).
                user_agent: HTTP User-Agent header (max 512 chars).
                entry_hash: SHA-256 hex of this row chained to prev_hash.
                prev_hash: entry_hash of the preceding audit entry.
                created_at: UTC timestamp with server default (tamper-proof).
            \"\"\"

            __tablename__ = "audit_logs"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            # created_at is part of the composite PK because PostgreSQL requires
            # the partition key to be included in any unique constraint on a
            # partitioned table (PARTITION BY RANGE (created_at) below).
            entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
            entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
            action: Mapped[str] = mapped_column(String(32), nullable=False)
            user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
            auth_method: Mapped[str | None] = mapped_column(
                String(32), nullable=True,
                comment="Authentication method: password, api_key, oauth2, mfa"
            )
            before_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
            after_values: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
            ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
            user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
            entry_hash: Mapped[str | None] = mapped_column(
                String(64), nullable=True, comment="SHA-256 hex of this row chained to prev"
            )
            prev_hash: Mapped[str | None] = mapped_column(
                String(64), nullable=True, comment="entry_hash of the preceding audit entry"
            )
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True),
                server_default=func.now(),
                nullable=False,
                primary_key=True,
            )

            __table_args__ = (
                Index("ix_audit_entity", "entity_type", "entity_id", "created_at"),
                Index("ix_audit_user", "user_id", "created_at"),
                Index("ix_audit_action", "action", "created_at"),
                CheckConstraint(
                    "action IN ('create','update','delete','soft_delete','restore','read')",
                    name="ck_audit_action",
                ),
                {"postgresql_partition_by": "RANGE (created_at)"},
            )
        """)
    dest.write_text(content)


def _write_audit_context(dest: Path) -> None:
    """Write ``app/core/audit_context.py`` with request-scoped context vars.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Request-scoped context for audit logging via Python contextvars.

        Set once per request by AuditContextMiddleware; read by audit listeners.
        \"\"\"

        from __future__ import annotations

        import contextvars
        import uuid
        from typing import Any

        _current_user_id: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
            "audit_user_id", default=None
        )
        _current_request_meta: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
            "audit_request_meta", default={}
        )


        def set_audit_context(user_id: uuid.UUID | None, meta: dict[str, Any]) -> None:
            \"\"\"Set user_id and request metadata for the current async context.

            Args:
                user_id: UUID of the authenticated user, or None for anonymous.
                meta: Dict with optional 'ip_address' and 'user_agent' keys.
            \"\"\"
            _current_user_id.set(user_id)
            _current_request_meta.set(meta)


        def get_audit_context() -> tuple[uuid.UUID | None, dict[str, Any]]:
            \"\"\"Return (user_id, meta) for the current request context.

            Returns:
                Tuple of (user_id, meta_dict).
            \"\"\"
            return _current_user_id.get(), _current_request_meta.get()


        def clear_audit_context() -> None:
            \"\"\"Reset audit context. Call in finally blocks during testing.\"\"\"
            _current_user_id.set(None)
            _current_request_meta.set({})
        """)
    dest.write_text(content)


def _write_audit_listeners(dest: Path, model_pairs: list[tuple[str, str]]) -> None:
    """Write ``app/core/audit_listeners.py`` with before_flush event listener.

    The listener intercepts every flush cycle and emits AuditLog rows for
    tracked models.  SHA-256 hash chain links each entry to the previous one.

    Args:
        dest: Absolute destination path.
        model_pairs: ``(snake_stem, PascalName)`` pairs for models to register.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    model_imports = "\n".join(
        f"from app.models.{stem} import {pascal}" for stem, pascal in model_pairs
    )
    audited_set = ", ".join(pascal for _stem, pascal in model_pairs)

    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy Session.before_flush listeners for automatic audit capture.

        Registered once at startup via register_audit_listeners().
        \"\"\"

        from __future__ import annotations

        import hashlib
        import json
        import uuid
        from datetime import datetime, timezone
        from typing import Any

        from sqlalchemy import event, inspect
        from sqlalchemy.orm import Session as _OrmSession

        from app.core.audit_context import get_audit_context
        from app.models.audit_log import AuditLog
        MODELIMPORTS

        AUDITED_MODELS: set[type] = {AUDITEDSET}
        _HASH_CHAIN_ENABLED: bool = True


        def _serialize(value: Any) -> Any:
            \"\"\"Serialize a value to a JSON-safe type for JSONB storage.

            Handles date, datetime, time, UUID, Decimal, bytes, and Enum —
            the non-JSON-native types commonly found in ORM columns. Unknown
            types fall through to ``str(value)`` to avoid crashing the flush.

            Args:
                value: Any Python value.

            Returns:
                JSON-serializable equivalent.
            \"\"\"
            import datetime as _dt
            import decimal as _dec
            import enum as _enum
            if value is None or isinstance(value, (str, int, float, bool)):
                return value
            if isinstance(value, (_dt.datetime, _dt.date, _dt.time)):
                return value.isoformat()
            if isinstance(value, uuid.UUID):
                return str(value)
            if isinstance(value, _dec.Decimal):
                return str(value)
            if isinstance(value, bytes):
                return value.hex()
            if isinstance(value, _enum.Enum):
                return value.value
            if isinstance(value, (list, tuple)):
                return [_serialize(v) for v in value]
            if isinstance(value, dict):
                return {str(k): _serialize(v) for k, v in value.items()}
            return str(value)


        def _compute_diff(target: Any) -> tuple[dict[str, Any], dict[str, Any]]:
            \"\"\"Return (before, after) dicts with only changed fields.

            Args:
                target: SQLAlchemy ORM instance being flushed.

            Returns:
                Tuple of (before_values, after_values) dicts.
            \"\"\"
            state = inspect(target)
            before: dict[str, Any] = {}
            after: dict[str, Any] = {}
            for attr in state.attrs:
                hist = attr.load_history()
                if hist.has_changes():
                    before[attr.key] = _serialize(hist.deleted[0] if hist.deleted else None)
                    after[attr.key] = _serialize(hist.added[0] if hist.added else None)
            return before, after


        def _full_snapshot(target: Any) -> dict[str, Any]:
            \"\"\"Return all column values as a JSON-safe dict.

            Args:
                target: SQLAlchemy ORM instance.

            Returns:
                Dict of all attribute values.
            \"\"\"
            state = inspect(target)
            return {
                attr.key: _serialize(getattr(target, attr.key, None))
                for attr in state.attrs
            }


        def _classify_action(before: dict[str, Any], after: dict[str, Any]) -> str:
            \"\"\"Detect soft_delete / restore from is_deleted transitions.

            Args:
                before: Pre-flush column values.
                after: Post-flush column values.

            Returns:
                Action label string.
            \"\"\"
            if "is_deleted" in before and "is_deleted" in after:
                if before["is_deleted"] is False and after["is_deleted"] is True:
                    return "soft_delete"
                if before["is_deleted"] is True and after["is_deleted"] is False:
                    return "restore"
            return "update"


        def _get_prev_hash(session: _OrmSession) -> str | None:
            \"\"\"Fetch the entry_hash of the most recent persisted audit entry.

            Queries the database directly so the chain is correct even when
            earlier audit entries from the same request were already flushed
            and are no longer in ``session.new``.

            Args:
                session: Active SQLAlchemy session.

            Returns:
                SHA-256 hex string or None if the audit_logs table is empty.
            \"\"\"
            from sqlalchemy import text as _text
            row = session.execute(
                _text(
                    "SELECT entry_hash FROM audit_logs "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            ).first()
            return row[0] if row else None


        def _compute_entry_hash(entry: AuditLog) -> str:
            \"\"\"Compute SHA-256 hash of an audit entry chained to its predecessor.

            Args:
                entry: AuditLog instance (must have all fields set except entry_hash).

            Returns:
                64-character hex digest.
            \"\"\"
            payload = json.dumps(
                {
                    "id": str(entry.id),
                    "entity_type": entry.entity_type,
                    "entity_id": str(entry.entity_id),
                    "action": entry.action,
                    "user_id": str(entry.user_id) if entry.user_id else None,
                    "before_values": entry.before_values,
                    "after_values": entry.after_values,
                    "ip_address": entry.ip_address,
                    "prev_hash": entry.prev_hash,
                },
                sort_keys=True,
                default=str,
            )
            return hashlib.sha256(payload.encode()).hexdigest()


        def _emit_audit(
            session: _OrmSession,
            target: Any,
            action: str,
            before: dict[str, Any] | None,
            after: dict[str, Any] | None,
        ) -> None:
            \"\"\"Create and add an AuditLog entry to the session.

            Args:
                session: Active SQLAlchemy session.
                target: ORM instance being audited.
                action: Action label (create/update/delete/soft_delete/restore).
                before: Before-values dict or None for create.
                after: After-values dict or None for delete.
            \"\"\"
            user_id, meta = get_audit_context()
            prev_hash = _get_prev_hash(session) if _HASH_CHAIN_ENABLED else None
            entry = AuditLog(
                entity_type=type(target).__name__.lower(),
                entity_id=str(getattr(target, "id", "")),
                action=action,
                user_id=user_id,
                before_values=before or None,
                after_values=after or None,
                ip_address=meta.get("ip_address"),
                user_agent=meta.get("user_agent"),
                prev_hash=prev_hash,
            )
            if _HASH_CHAIN_ENABLED:
                entry.entry_hash = _compute_entry_hash(entry)
            session.add(entry)


        @event.listens_for(_OrmSession, "before_flush")
        def _audit_before_flush(session: _OrmSession, flush_context: Any, instances: Any) -> None:
            \"\"\"Intercept every flush and emit audit entries for tracked models.

            Args:
                session: The SQLAlchemy session being flushed.
                flush_context: Internal flush context (unused).
                instances: Specific instances being flushed (unused; we inspect session directly).
            \"\"\"
            for target in list(session.new):
                try:
                    is_audited = type(target) in AUDITED_MODELS
                except TypeError:
                    continue
                if is_audited:
                    _emit_audit(session, target, "create", None, _full_snapshot(target))
            for target in list(session.dirty):
                try:
                    is_audited = type(target) in AUDITED_MODELS
                except TypeError:
                    continue
                if is_audited:
                    before, after = _compute_diff(target)
                    if before:
                        action = _classify_action(before, after)
                        _emit_audit(session, target, action, before, after)
            for target in list(session.deleted):
                try:
                    is_audited = type(target) in AUDITED_MODELS
                except TypeError:
                    continue
                if is_audited:
                    _emit_audit(session, target, "delete", _full_snapshot(target), None)


        def register_audit_listeners(hash_chain: bool = True) -> None:
            \"\"\"Activate the audit listener. Call once at application startup.

            Args:
                hash_chain: Enable SHA-256 hash chaining (default True).
            \"\"\"
            global _HASH_CHAIN_ENABLED
            _HASH_CHAIN_ENABLED = hash_chain
        """)

    content = (
        content
        .replace("MODELIMPORTS", model_imports)
        .replace("{AUDITEDSET}", "{" + audited_set + "}")
    )
    dest.write_text(content)


def _write_audit_verifier(dest: Path) -> None:
    """Write ``app/core/audit_verifier.py`` for hash-chain integrity verification.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Verify integrity of the audit log hash chain over a given time range.\"\"\"

        from __future__ import annotations

        import hashlib
        import json
        from dataclasses import dataclass, field
        from datetime import datetime

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.audit_log import AuditLog


        @dataclass
        class VerificationResult:
            \"\"\"Result of a hash-chain verification run.

            Attributes:
                total_entries: Number of entries examined.
                broken_at: Entry id where the chain first breaks, or None.
                is_intact: True if every hash in the range is valid.
                errors: Human-readable descriptions of any integrity violations.
            \"\"\"

            total_entries: int = 0
            broken_at: str | None = None
            is_intact: bool = True
            errors: list[str] = field(default_factory=list)


        async def verify_hash_chain(
            session: AsyncSession,
            from_dt: datetime,
            to_dt: datetime,
        ) -> VerificationResult:
            \"\"\"Re-compute SHA-256 hashes and verify chain continuity.

            Args:
                session: Async SQLAlchemy session.
                from_dt: Start of the verification range (inclusive).
                to_dt: End of the verification range (inclusive).

            Returns:
                VerificationResult with is_intact=True if all hashes are valid.
            \"\"\"
            stmt = (
                select(AuditLog)
                .where(AuditLog.created_at.between(from_dt, to_dt))
                .order_by(AuditLog.created_at)
            )
            rows = (await session.execute(stmt)).scalars().all()
            result = VerificationResult(total_entries=len(rows))
            prev_hash: str | None = None
            for row in rows:
                ok, error_msg = _verify_row(row, prev_hash)
                if not ok:
                    result.is_intact = False
                    result.broken_at = str(row.id)
                    result.errors.append(error_msg)
                    break
                prev_hash = row.entry_hash
            return result


        def _compute_row_hash(row: AuditLog) -> str:
            \"\"\"Re-compute the expected SHA-256 hash for an AuditLog row.

            Args:
                row: AuditLog ORM instance.

            Returns:
                Hex-encoded SHA-256 digest string.
            \"\"\"
            payload = json.dumps(
                {
                    "id": str(row.id),
                    "entity_type": row.entity_type,
                    "entity_id": str(row.entity_id),
                    "action": row.action,
                    "user_id": str(row.user_id) if row.user_id else None,
                    "before_values": row.before_values,
                    "after_values": row.after_values,
                    "ip_address": row.ip_address,
                    "prev_hash": row.prev_hash,
                },
                sort_keys=True,
                default=str,
            )
            return hashlib.sha256(payload.encode()).hexdigest()


        def _verify_row(row: AuditLog, prev_hash: str | None) -> tuple[bool, str]:
            \"\"\"Verify one AuditLog row against its stored hash and the chain link.

            Args:
                row: AuditLog ORM instance to verify.
                prev_hash: entry_hash of the preceding row, or None for first row.

            Returns:
                Tuple of (is_valid, error_message).  error_message is empty on success.
            \"\"\"
            expected_hash = _compute_row_hash(row)
            if row.entry_hash != expected_hash:
                return False, (
                    f"Hash mismatch at id={row.id}: stored={row.entry_hash!r} "
                    f"expected={expected_hash!r}"
                )
            if prev_hash is not None and row.prev_hash != prev_hash:
                return False, (
                    f"Chain break at id={row.id}: prev_hash={row.prev_hash!r} "
                    f"expected={prev_hash!r}"
                )
            return True, ""
        """)
    dest.write_text(content)


def _write_audit_schemas(dest: Path) -> None:
    """Write ``app/schemas/audit_log.py`` with filter/page/verify schemas.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for the audit log query API.\"\"\"

        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from pydantic import BaseModel, ConfigDict, Field


        class AuditLogFilter(BaseModel):
            \"\"\"Filter parameters for the audit log query endpoint.

            Attributes:
                entity_type: Filter by model name (e.g. 'item').
                entity_id: Filter by specific entity primary key.
                actor_id: Filter by the user who performed the action.
                action: Filter by action type.
                from_dt: Start of time range (inclusive).
                to_dt: End of time range (inclusive).
            \"\"\"

            entity_type: str | None = None
            entity_id: str | None = None
            actor_id: uuid.UUID | None = None
            action: str | None = None
            from_dt: datetime | None = None
            to_dt: datetime | None = None


        class AuditLogEntry(BaseModel):
            \"\"\"Public representation of a single audit log entry.

            Attributes:
                id: UUID primary key.
                entity_type: Lowercase model class name.
                entity_id: String PK of the audited entity.
                action: Action performed.
                user_id: UUID of the actor, if known.
                before_values: Changed fields before the operation.
                after_values: Changed fields after the operation.
                ip_address: Client IP address, if captured.
                entry_hash: SHA-256 chain hash for tamper detection.
                created_at: UTC timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            entity_type: str
            entity_id: str
            action: str
            user_id: uuid.UUID | None
            before_values: dict[str, Any] | None
            after_values: dict[str, Any] | None
            ip_address: str | None
            entry_hash: str | None
            created_at: datetime


        class AuditLogPage(BaseModel):
            \"\"\"Paginated list of audit entries.

            Attributes:
                items: Page of audit entries.
                total: Total matching entries (before pagination).
                offset: Current page offset.
                limit: Current page size.
            \"\"\"

            items: list[AuditLogEntry]
            total: int
            offset: int
            limit: int


        class VerifyRequest(BaseModel):
            \"\"\"Request body for the hash-chain verification endpoint.

            Attributes:
                from_dt: Start of the verification range (inclusive).
                to_dt: End of the verification range (inclusive).
            \"\"\"

            from_dt: datetime = Field(..., description="Start of verification range (UTC)")
            to_dt: datetime = Field(..., description="End of verification range (UTC)")
        """)
    dest.write_text(content)


def _write_audit_crud(dest: Path) -> None:
    """Write ``app/crud/audit_log.py`` with read-only query function.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Read-only CRUD for the audit log. Auditors only; no write path.\"\"\"

        from __future__ import annotations

        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func, select, text
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.audit_log import AuditLog
        from app.schemas.audit_log import AuditLogFilter, AuditLogPage, AuditLogEntry


        async def query_audit_logs(
            session: AsyncSession,
            filters: AuditLogFilter,
            offset: int = 0,
            limit: int = 50,
        ) -> AuditLogPage:
            \"\"\"Return paginated audit entries matching the given filters.

            Args:
                session: Async SQLAlchemy session.
                filters: AuditLogFilter with optional predicates.
                offset: Pagination offset.
                limit: Page size (max 500).

            Returns:
                AuditLogPage with items, total, offset, and limit.
            \"\"\"
            stmt = select(AuditLog)

            if filters.entity_type:
                stmt = stmt.where(AuditLog.entity_type == filters.entity_type)
            if filters.entity_id:
                stmt = stmt.where(AuditLog.entity_id == str(filters.entity_id))
            if filters.actor_id:
                stmt = stmt.where(AuditLog.user_id == filters.actor_id)
            if filters.action:
                stmt = stmt.where(AuditLog.action == filters.action)
            if filters.from_dt:
                stmt = stmt.where(AuditLog.created_at >= filters.from_dt)
            if filters.to_dt:
                stmt = stmt.where(AuditLog.created_at <= filters.to_dt)

            count_stmt = select(func.count()).select_from(stmt.subquery())
            total = (await session.execute(count_stmt)).scalar_one()

            stmt = stmt.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
            rows = (await session.execute(stmt)).scalars().all()

            items = [AuditLogEntry.model_validate(r) for r in rows]
            return AuditLogPage(items=items, total=total, offset=offset, limit=limit)


        async def purge_expired_audit_logs(
            session: AsyncSession,
            retain_days: int,
        ) -> int:
            \"\"\"Delete audit log entries older than *retain_days* days.

            NEVER deletes rows newer than the computed cutoff timestamp.
            The cutoff is ``now() - retain_days`` so only rows strictly older
            than the retention window are removed.

            Args:
                session: Async SQLAlchemy session (caller must commit).
                retain_days: Number of days to retain.  Rows with
                    ``created_at < now() - interval '{retain_days} days'``
                    are deleted.

            Returns:
                Number of rows deleted.
            \"\"\"
            cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
            result = await session.execute(
                text(
                    "DELETE FROM audit_logs WHERE created_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            return result.rowcount
        """)
    dest.write_text(content)


def _patch_deps(deps_file: Path) -> None:
    """Add CurrentAuditor dependency to ``app/api/deps.py``.

    Args:
        deps_file: Path to ``app/api/deps.py``.
    """
    src = deps_file.read_text()
    if "CurrentAuditor" in src:
        return

    auditor_dep = textwrap.dedent("""\


        # ---------------------------------------------------------------------------
        # Auditor dependency — added by add_audit_log tool
        # ---------------------------------------------------------------------------
        from fastapi import HTTPException, status as _http_status

        def _require_auditor(current_user: CurrentUser) -> None:
            \"\"\"Raise 403 unless the user is a superuser or has role=auditor.

            Args:
                current_user: Authenticated user from the standard CurrentUser dep.

            Raises:
                HTTPException: 403 if the user lacks auditor privileges.
            \"\"\"
            is_super = getattr(current_user, "is_superuser", False)
            role = getattr(current_user, "role", None)
            if not is_super and role != "auditor":
                raise _http_status.HTTP_403_FORBIDDEN
            return None


        CurrentAuditor = Annotated[None, Depends(_require_auditor)]
        """)

    if "Annotated" not in src:
        src = "from typing import Annotated\n" + src
    if "Depends" not in src:
        src = src.replace(
            "from fastapi import",
            "from fastapi import Depends,",
        )

    deps_file.write_text(src + auditor_dep)


def _write_audit_routes(dest: Path) -> None:
    """Write ``app/api/routes/audit_logs.py`` with read-only endpoints.

    Args:
        dest: Absolute destination path.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"Read-only audit log endpoints. Accessible only to auditors and superusers.

        Endpoints:
        - GET  /audit-logs/         — paginated query with filters
        - POST /audit-logs/verify   — hash-chain integrity verification
        \"\"\"

        from __future__ import annotations

        from datetime import datetime

        from fastapi import APIRouter, Depends, Query
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.api.deps import CurrentAuditor, get_async_session
        from app.core.audit_verifier import VerificationResult, verify_hash_chain
        from app.crud.audit_log import query_audit_logs
        from app.schemas.audit_log import AuditLogFilter, AuditLogPage, VerifyRequest

        router = APIRouter(prefix="/audit-logs", tags=["audit"])


        @router.get("/", response_model=AuditLogPage)
        async def list_audit_logs(
            session: AsyncSession = Depends(get_async_session),
            _auditor: None = Depends(CurrentAuditor),
            entity_type: str | None = Query(None, description="Filter by model name"),
            entity_id: str | None = Query(None, description="Filter by entity ID"),
            actor_id: str | None = Query(None, description="Filter by user UUID"),
            action: str | None = Query(None, description="Filter by action"),
            from_dt: datetime | None = Query(None, description="Start timestamp (UTC)"),
            to_dt: datetime | None = Query(None, description="End timestamp (UTC)"),
            offset: int = Query(0, ge=0),
            limit: int = Query(50, ge=1, le=500),
        ) -> AuditLogPage:
            \"\"\"List audit log entries with optional filters. Auditor/superuser only.

            Args:
                session: Injected async DB session.
                _auditor: Auditor privilege check (raises 403 if insufficient).
                entity_type: Filter by lowercase model name.
                entity_id: Filter by entity primary key string.
                actor_id: Filter by actor user UUID.
                action: Filter by action type.
                from_dt: Start of time range.
                to_dt: End of time range.
                offset: Pagination offset.
                limit: Page size (1–500).
            \"\"\"
            import uuid as _u
            filters = AuditLogFilter(
                entity_type=entity_type,
                entity_id=entity_id,
                actor_id=_u.UUID(actor_id) if actor_id else None,
                action=action,
                from_dt=from_dt,
                to_dt=to_dt,
            )
            return await query_audit_logs(session, filters, offset=offset, limit=limit)


        @router.post("/verify", response_model=VerificationResult)
        async def verify_audit_chain(
            body: VerifyRequest,
            session: AsyncSession = Depends(get_async_session),
            _auditor: None = Depends(CurrentAuditor),
        ) -> VerificationResult:
            \"\"\"Re-compute and verify the SHA-256 hash chain over a time range.

            Args:
                body: VerifyRequest with from_dt and to_dt.
                session: Injected async DB session.
                _auditor: Auditor privilege check.

            Returns:
                VerificationResult with is_intact flag and any error messages.
            \"\"\"
            return await verify_hash_chain(session, from_dt=body.from_dt, to_dt=body.to_dt)
        """)
    dest.write_text(content)


def _patch_main(main_file: Path) -> None:
    """Register audit listeners import in main.py.

    Args:
        main_file: Path to ``app/main.py``.
    """
    src = main_file.read_text()
    if "audit_listeners" in src:
        return

    marker = "from app.core.logging import configure_logging"
    audit_import = "\nimport app.core.audit_listeners  # noqa: F401  — activates audit before_flush listener"
    if marker in src:
        src = src.replace(marker, marker + audit_import)
    else:
        src = "import app.core.audit_listeners  # noqa: F401\n" + src

    main_file.write_text(src)


def _write_migration(versions_dir: Path) -> Path:
    """Generate an Alembic migration for audit_logs with partition + trigger.

    Creates 3 initial monthly child partitions (previous, current, and next
    month) computed dynamically at tool-run time so INSERT never fails on a
    missing partition.  Uses ``prevent_audit_mutation`` PL/pgSQL function and
    ``trg_audit_log_immutable`` trigger to enforce row immutability at the DB
    level.

    Args:
        versions_dir: ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    from datetime import datetime, timezone
    from calendar import monthrange

    rev_id = "add_audit_log"
        # Find the true HEAD of the migration chain (not just the alphabetically last file)
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    # --- Compute 3 monthly partitions: previous, current, next ---------------
    def _month_bounds(year: int, month: int) -> tuple[str, str]:
        """Return (first_day, exclusive_upper) for the given month."""
        _, last_day = monthrange(year, month)
        start = f"{year:04d}-{month:02d}-01"
        # exclusive upper: first day of next month
        next_year, next_month = (year, month + 1) if month < 12 else (year + 1, 1)
        end = f"{next_year:04d}-{next_month:02d}-01"
        return start, end

    now = datetime.now(timezone.utc)
    # previous month
    prev_year, prev_month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    # next month
    next_year, next_month = (now.year, now.month + 1) if now.month < 12 else (now.year + 1, 1)

    partitions = [
        (f"y{prev_year}m{prev_month:02d}", *_month_bounds(prev_year, prev_month)),
        (f"y{now.year}m{now.month:02d}", *_month_bounds(now.year, now.month)),
        (f"y{next_year}m{next_month:02d}", *_month_bounds(next_year, next_month)),
    ]

    # Indentation: 4 spaces (matches dedented template where def body uses 4 spaces)
    partition_creates = "\n".join(
        f'    op.execute(\"\"\"\n'
        f'        CREATE TABLE audit_logs_{name}\n'
        f'        PARTITION OF audit_logs\n'
        f"        FOR VALUES FROM ('{frm}') TO ('{to}')\n"
        f'    \"\"\")'
        for name, frm, to in partitions
    )
    partition_drops = "\n".join(
        f'    op.drop_table("audit_logs_{name}")'
        for name, _, __ in reversed(partitions)
    )

    content = textwrap.dedent("""\
        \"\"\"Create audit_logs partitioned table with immutability trigger.

        Revision ID: add_audit_log
        Revises: DOWN_REV
        Create Date: auto-generated by add_audit_log tool
        \"\"\"

        from __future__ import annotations

        from alembic import op

        revision = "add_audit_log"
        down_revision = "DOWN_REV"
        branch_labels = None
        depends_on = None

        IMMUTABLE_TRIGGER_SQL = \"\"\"
        CREATE OR REPLACE FUNCTION prevent_audit_mutation() RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs rows are immutable';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_audit_log_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_mutation();
        \"\"\"

        IMMUTABLE_TRIGGER_DROP = \"\"\"
        DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_logs;
        DROP FUNCTION IF EXISTS prevent_audit_mutation();
        \"\"\"


        def upgrade() -> None:
            \"\"\"Create partitioned audit_logs table, indexes, and immutability trigger.\"\"\"
            op.execute(\"\"\"
                CREATE TABLE audit_logs (
                    id UUID NOT NULL DEFAULT gen_random_uuid(),
                    entity_type VARCHAR(64) NOT NULL,
                    entity_id VARCHAR(64) NOT NULL,
                    action VARCHAR(32) NOT NULL,
                    user_id UUID,
                    before_values JSONB,
                    after_values JSONB,
                    ip_address INET,
                    user_agent VARCHAR(512),
                    entry_hash VARCHAR(64),
                    prev_hash VARCHAR(64),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT pk_audit_logs PRIMARY KEY (id, created_at),
                    CONSTRAINT ck_audit_action CHECK (
                        action IN ('create','update','delete','soft_delete','restore','read')
                    )
                ) PARTITION BY RANGE (created_at)
            \"\"\")
        PARTITION_CREATES_HERE
            op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id", "created_at"])
            op.create_index("ix_audit_user", "audit_logs", ["user_id", "created_at"])
            op.create_index("ix_audit_action", "audit_logs", ["action", "created_at"])
            op.execute(IMMUTABLE_TRIGGER_SQL)


        def downgrade() -> None:
            \"\"\"Drop audit_logs table, partitions, indexes, and trigger.\"\"\"
            op.execute(IMMUTABLE_TRIGGER_DROP)
            op.drop_index("ix_audit_action", table_name="audit_logs")
            op.drop_index("ix_audit_user", table_name="audit_logs")
            op.drop_index("ix_audit_entity", table_name="audit_logs")
        PARTITION_DROPS_HERE
            op.drop_table("audit_logs")
        """) \
        .replace("DOWN_REV", down_rev) \
        .replace("PARTITION_CREATES_HERE\n", partition_creates + "\n") \
        .replace("PARTITION_DROPS_HERE\n", partition_drops + "\n")

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
