"""TOOL-015: add_webhook_sender — add outbound webhook delivery to a FastAPI project.

Creates ``WebhookEndpoint`` and ``WebhookDelivery`` models, an HMAC-SHA256
signer, a fixed exponential-backoff schedule, an ARQ worker, CRUD helpers,
admin routes, Pydantic schemas, and an Alembic migration.  The ``send_webhook``
public helper enqueues delivery jobs so callers never block.

Auto-disable: after ``disable_after_consecutive_failures`` consecutive failures
the endpoint's status is set to ``"disabled"`` and no further retries are
attempted, preventing the sender from wasting cycles on a dead partner.

The tool is idempotent: a second run detects the ``WebhookEndpoint`` model
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.realtime.add_webhook_sender import add_webhook_sender

    result = add_webhook_sender(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/models/webhook.py", …]
    print(result.next_steps)    # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_webhook_sender",
    "description": "Add outbound webhook delivery system with retry, signature, and delivery log.",
    "tags": ["extend", "realtime"],
    "entry": "add_webhook_sender",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_webhook_sender(
    inp: ToolInput,
    *,
    max_attempts: int = 7,
    http_timeout_seconds: float = 10.0,
    max_payload_bytes: int = 262_144,
    disable_after_consecutive_failures: int = 12,
) -> ToolResult:
    """Add outbound webhook delivery to a FastAPI project.

    Creates models, signer, backoff schedule, ARQ worker, CRUD, routes,
    schemas, and an Alembic migration.  Patches ``app/core/config.py`` and
    ``app/api/main.py``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        max_attempts: Total delivery attempts including the first (default 7).
        http_timeout_seconds: Per-request HTTP timeout in seconds (default 10.0).
        max_payload_bytes: Hard cap on event payload size in bytes (default 262144).
        disable_after_consecutive_failures: Auto-disable threshold (default 12).

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

    # --- Pre-flight: already installed? ------------------------------------
    model_file = app_dir / "models" / "webhook.py"
    if model_file.exists() and "WebhookEndpoint" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["WebhookEndpoint already present — webhook sender is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create WebhookEndpoint/WebhookDelivery models,",
                "         signer, backoff, ARQ worker, CRUD, routes, schemas, migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 – models
    # If the project already has a webhook.py (e.g. a user-defined Webhook model),
    # APPEND the sender models to the existing file instead of overwriting it.
    # This preserves the user's Webhook class while adding WebhookEndpoint / WebhookDelivery.
    if model_file.exists():
        _append_webhook_models(model_file)
        files_modified.append(str(model_file))
    else:
        _write_webhook_models(model_file)
        files_created.append(str(model_file))

    # Register webhook sender models in app/models/__init__.py for
    # metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [
            ("webhook", "WebhookEndpoint"),
            ("webhook", "WebhookDelivery"),
        ],
    )

    # Step 2 – signer
    webhooks_core_dir = app_dir / "core" / "webhooks"
    webhooks_core_dir.mkdir(parents=True, exist_ok=True)
    init_f = webhooks_core_dir / "__init__.py"
    if not init_f.exists():
        init_f.write_text('"""Outbound webhooks sub-package."""\n')
        files_created.append(str(init_f))

    signer_file = webhooks_core_dir / "signer.py"
    _write_signer(signer_file)
    files_created.append(str(signer_file))

    # Step 3 – backoff schedule
    backoff_file = webhooks_core_dir / "backoff.py"
    _write_backoff(backoff_file)
    files_created.append(str(backoff_file))

    # Step 4 – sender helper
    sender_file = webhooks_core_dir / "sender.py"
    _write_sender(sender_file, max_payload_bytes)
    files_created.append(str(sender_file))

    # Step 5 – CRUD
    # If app/crud/webhook.py already exists (generated from user's Webhook model),
    # append the sender CRUD helpers rather than overwriting.
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "webhook.py"
    if crud_file.exists():
        _append_webhook_crud(crud_file)
        files_modified.append(str(crud_file))
    else:
        _write_webhook_crud(crud_file)
        files_created.append(str(crud_file))

    # Step 6 – schemas
    # Guard: append sender schemas if app/schemas/webhook.py already exists
    # (generated from user's Webhook model) to avoid overwriting user code.
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "webhook.py"
    if schema_file.exists() and "WebhookEndpointCreate" not in schema_file.read_text():
        _append_webhook_schemas(schema_file)
        files_modified.append(str(schema_file))
    elif not schema_file.exists():
        _write_webhook_schemas(schema_file)
        files_created.append(str(schema_file))

    # Step 7 – ARQ worker
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    worker_init = workers_dir / "__init__.py"
    if not worker_init.exists():
        worker_init.write_text('"""Background workers sub-package."""\n')
        files_created.append(str(worker_init))
    worker_file = workers_dir / "webhook_worker.py"
    _write_webhook_worker(worker_file, http_timeout_seconds, disable_after_consecutive_failures)
    files_created.append(str(worker_file))

    # Step 8 – routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "webhooks.py"
    _write_webhook_routes(route_file)
    files_created.append(str(route_file))

    # Step 9 – migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_webhook_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 10 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file, max_attempts, http_timeout_seconds,
            max_payload_bytes, disable_after_consecutive_failures,
        )
        files_modified.append(str(config_file))

    # Step 11 – register webhooks router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    # Validate written files
    for path_str in files_created:
        _assert_parses(Path(path_str))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Outbound webhook sender added: models, signer, backoff, ARQ worker, CRUD, routes.",
            f"Max attempts: {max_attempts}.  "
            f"Auto-disable after: {disable_after_consecutive_failures} consecutive failures.",
            f"Payload cap: {max_payload_bytes} bytes.  HTTP timeout: {http_timeout_seconds}s.",
            "Call: await send_webhook('event.type', payload) to enqueue delivery.",
            "Secret is returned ONLY at endpoint creation; excluded from list responses.",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set REDIS_URL in .env — ARQ worker requires Redis for job queue.",
            "Run the ARQ worker: arq app.workers.webhook_worker.WorkerSettings",
            "Restart the application so the webhooks router is active.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each < 50 LOC
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


def _write_webhook_models(dest: Path) -> None:
    """Write ``app/models/webhook.py`` with ``WebhookEndpoint`` and ``WebhookDelivery``.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy models for outbound webhook endpoints and delivery attempts.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            JSON,
            CheckConstraint,
            DateTime,
            ForeignKey,
            Integer,
            String,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column, relationship

        from app.models.base import Base


        class WebhookEndpoint(Base):
            \"\"\"A subscriber's registered webhook endpoint.

            Attributes:
                id: UUID primary key.
                url: Delivery URL (must be http or https).
                description: Optional human-readable description.
                events: JSON list of subscribed event type strings.
                secret: HMAC signing secret (never returned after creation).
                status: One of active / disabled / suspended.
                consecutive_failures: Counter reset to 0 on any 2xx response.
                last_success_at: UTC timestamp of last successful delivery.
                last_failure_at: UTC timestamp of last failed delivery attempt.
                user_id: Owner's user UUID (CASCADE delete).
                created_at: Creation timestamp.
            \"\"\"

            __tablename__ = "webhook_endpoints"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            url: Mapped[str] = mapped_column(String(2048), nullable=False)
            description: Mapped[str | None] = mapped_column(String(500), nullable=True)
            events: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
            secret: Mapped[str] = mapped_column(String(128), nullable=False)
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="active"
            )
            consecutive_failures: Mapped[int] = mapped_column(
                Integer, nullable=False, server_default="0"
            )
            last_success_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )
            last_failure_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )
            user_id: Mapped[uuid.UUID] = mapped_column(
                Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
            )
            created_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )

            deliveries: Mapped[list["WebhookDelivery"]] = relationship(
                back_populates="endpoint", cascade="all, delete-orphan"
            )

            __table_args__ = (
                CheckConstraint(
                    "status IN ('active','disabled','suspended')",
                    name="ck_webhook_endpoints_status",
                ),
                CheckConstraint(
                    "url LIKE 'http://%' OR url LIKE 'https://%'",
                    name="ck_webhook_endpoints_url_format",
                ),
            )


        class WebhookDelivery(Base):
            \"\"\"A single webhook delivery attempt record.

            Attributes:
                id: UUID primary key.
                endpoint_id: FK to the parent WebhookEndpoint.
                event_id: Logical event UUID shared across all deliveries of one event.
                event_type: String event type (e.g. ``item.created``).
                payload: JSON event payload.
                status: One of pending / succeeded / failed / dead.
                attempt_number: 1-indexed delivery attempt counter.
                http_status: HTTP response status code, if available.
                response_body: First 4096 chars of the response body.
                error: Error summary string (max 500 chars).
                scheduled_at: When this delivery was created/scheduled.
                delivered_at: UTC timestamp of successful delivery.
            \"\"\"

            __tablename__ = "webhook_deliveries"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            endpoint_id: Mapped[uuid.UUID] = mapped_column(
                Uuid,
                ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            )
            event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
            event_type: Mapped[str] = mapped_column(String(127), nullable=False)
            payload: Mapped[dict] = mapped_column(JSON, nullable=False)
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="pending"
            )
            attempt_number: Mapped[int] = mapped_column(
                Integer, nullable=False, server_default="0"
            )
            http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
            response_body: Mapped[str | None] = mapped_column(String(4096), nullable=True)
            error: Mapped[str | None] = mapped_column(String(500), nullable=True)
            scheduled_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False
            )
            delivered_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            endpoint: Mapped["WebhookEndpoint"] = relationship(back_populates="deliveries")

            __table_args__ = (
                CheckConstraint(
                    "status IN ('pending','succeeded','failed','dead')",
                    name="ck_webhook_deliveries_status",
                ),
            )
        """)
    dest.write_text(content)


def _append_webhook_models(dest: Path) -> None:
    """Append ``WebhookEndpoint`` and ``WebhookDelivery`` to an existing models file.

    Called when ``app/models/webhook.py`` already exists (e.g. the user has their
    own ``Webhook`` model).  The new classes are appended so that all existing code
    is preserved.

    Args:
        dest: Absolute path of the existing ``webhook.py`` model file.
    """
    existing = dest.read_text()
    # Build only the new class blocks — omit the file header (imports already there)
    classes_block = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Outbound webhook sender models — added by add_webhook_sender tool
        # ---------------------------------------------------------------------------
        import uuid as _wh_uuid
        from datetime import datetime as _wh_datetime
        from typing import TYPE_CHECKING as _WH_TYPE_CHECKING

        from sqlalchemy import (
            CheckConstraint as _wh_CC,
            DateTime as _wh_DT,
            ForeignKey as _wh_FK,
            Integer as _wh_Int,
            JSON as _wh_JSON,
            String as _wh_String,
            Uuid as _wh_Uuid,
        )
        from sqlalchemy.orm import Mapped as _wh_Mapped, mapped_column as _wh_mc, relationship as _wh_rel

        if _WH_TYPE_CHECKING:
            pass

        from app.models.base import Base as _wh_Base


        class WebhookEndpoint(_wh_Base):
            \"\"\"Registered outbound webhook endpoint.

            Attributes:
                id: Primary key.
                url: Target HTTPS URL to deliver events to.
                description: Optional human-readable description.
                events: JSON array of subscribed event type strings.
                secret: HMAC-SHA256 signing secret (write-once).
                status: Lifecycle state — active, disabled, or suspended.
                consecutive_failures: Auto-disable counter.
                user_id: Owner (FK to users.id).
            \"\"\"

            __tablename__ = "webhook_endpoints"

            id: _wh_Mapped[_wh_uuid.UUID] = _wh_mc(_wh_Uuid, primary_key=True, default=_wh_uuid.uuid4)
            url: _wh_Mapped[str] = _wh_mc(_wh_String(2048), nullable=False)
            description: _wh_Mapped[str | None] = _wh_mc(_wh_String(500), nullable=True)
            events: _wh_Mapped[list] = _wh_mc(_wh_JSON, server_default="[]", nullable=False)
            secret: _wh_Mapped[str] = _wh_mc(_wh_String(128), nullable=False)
            status: _wh_Mapped[str] = _wh_mc(_wh_String(16), server_default="active", nullable=False)
            consecutive_failures: _wh_Mapped[int] = _wh_mc(_wh_Int, server_default="0", nullable=False)
            last_success_at: _wh_Mapped[_wh_datetime | None] = _wh_mc(_wh_DT(timezone=True), nullable=True)
            last_failure_at: _wh_Mapped[_wh_datetime | None] = _wh_mc(_wh_DT(timezone=True), nullable=True)
            user_id: _wh_Mapped[_wh_uuid.UUID] = _wh_mc(
                _wh_Uuid, _wh_FK("users.id", ondelete="CASCADE"), nullable=False
            )
            created_at: _wh_Mapped[_wh_datetime] = _wh_mc(
                _wh_DT(timezone=True), server_default="now()", nullable=False
            )

            deliveries: _wh_Mapped[list["WebhookDelivery"]] = _wh_rel(
                "WebhookDelivery", back_populates="endpoint", cascade="all, delete-orphan"
            )

            __table_args__ = (
                _wh_CC("status IN ('active','disabled','suspended')", name="ck_webhook_endpoints_status"),
                _wh_CC("url LIKE 'http://%' OR url LIKE 'https://%'", name="ck_webhook_endpoints_url_format"),
            )


        class WebhookDelivery(_wh_Base):
            \"\"\"Individual delivery attempt for an outbound webhook event.

            Attributes:
                id: Primary key.
                endpoint_id: FK to the parent WebhookEndpoint.
                event_id: Stable UUID for the logical event (used for dedup).
                event_type: Dot-separated event type string.
                payload: JSON event payload.
                status: Delivery outcome — pending, succeeded, failed, dead.
                attempt_number: 1-based counter.
                http_status: HTTP response status code, nullable.
            \"\"\"

            __tablename__ = "webhook_deliveries"

            id: _wh_Mapped[_wh_uuid.UUID] = _wh_mc(_wh_Uuid, primary_key=True, default=_wh_uuid.uuid4)
            endpoint_id: _wh_Mapped[_wh_uuid.UUID] = _wh_mc(
                _wh_Uuid, _wh_FK("webhook_endpoints.id", ondelete="CASCADE"), nullable=False
            )
            event_id: _wh_Mapped[_wh_uuid.UUID] = _wh_mc(_wh_Uuid, nullable=False)
            event_type: _wh_Mapped[str] = _wh_mc(_wh_String(127), nullable=False)
            payload: _wh_Mapped[dict] = _wh_mc(_wh_JSON, nullable=False)
            status: _wh_Mapped[str] = _wh_mc(_wh_String(16), server_default="pending", nullable=False)
            attempt_number: _wh_Mapped[int] = _wh_mc(_wh_Int, server_default="0", nullable=False)
            http_status: _wh_Mapped[int | None] = _wh_mc(_wh_Int, nullable=True)
            response_body: _wh_Mapped[str | None] = _wh_mc(_wh_String(4096), nullable=True)
            error: _wh_Mapped[str | None] = _wh_mc(_wh_String(500), nullable=True)
            scheduled_at: _wh_Mapped[_wh_datetime | None] = _wh_mc(_wh_DT(timezone=True), nullable=True)
            delivered_at: _wh_Mapped[_wh_datetime | None] = _wh_mc(_wh_DT(timezone=True), nullable=True)

            endpoint: _wh_Mapped["WebhookEndpoint"] = _wh_rel("WebhookEndpoint", back_populates="deliveries")

            __table_args__ = (
                _wh_CC("status IN ('pending','succeeded','failed','dead')", name="ck_webhook_deliveries_status"),
            )
        """)
    dest.write_text(existing.rstrip("\n") + "\n" + classes_block)


def _write_signer(dest: Path) -> None:
    """Write ``app/core/webhooks/signer.py`` with HMAC helpers.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"HMAC-SHA256 signature helpers for outbound webhook payloads.

        Every outbound delivery attaches::

            X-Signature: t=<unix_seconds>,v1=<hex-hmac-sha256>

        The MAC is computed over ``f\"{ts}.\" + body_bytes``.  Receivers verify
        using the same construction, reject signatures older than 5 minutes to
        mitigate replay, and use ``hmac.compare_digest`` for constant-time comparison.
        \"\"\"
        from __future__ import annotations

        import hashlib
        import hmac
        import time
        from dataclasses import dataclass

        MAX_SIGNATURE_AGE_SECONDS = 300


        @dataclass(frozen=True)
        class SignatureHeader:
            \"\"\"Value object representing the parsed ``X-Signature`` header.

            Attributes:
                timestamp: Unix seconds when the signature was created.
                v1_hex: Hex-encoded HMAC-SHA256 digest.
            \"\"\"

            timestamp: int
            v1_hex: str

            def to_header_value(self) -> str:
                \"\"\"Serialize to the ``t=...,v1=...`` wire format.

                Returns:
                    Header string ready to send.
                \"\"\"
                return f"t={self.timestamp},v1={self.v1_hex}"


        def sign_payload(
            secret: str,
            body: bytes,
            timestamp: int | None = None,
        ) -> SignatureHeader:
            \"\"\"Compute a Stripe-style HMAC-SHA256 signature header.

            Args:
                secret: The endpoint's signing secret.
                body: The raw JSON request body bytes.
                timestamp: Unix seconds override (defaults to current time).

            Returns:
                A ``SignatureHeader`` with the computed MAC.

            Raises:
                ValueError: If *secret* is empty.
            \"\"\"
            if not secret:
                raise ValueError("secret must be non-empty")
            ts = timestamp if timestamp is not None else int(time.time())
            signed_payload = f"{ts}.".encode("utf-8") + body
            mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
            return SignatureHeader(timestamp=ts, v1_hex=mac)


        def parse_signature_header(header_value: str) -> SignatureHeader | None:
            \"\"\"Parse a ``t=...,v1=...`` header string.

            Args:
                header_value: Raw header string value.

            Returns:
                A ``SignatureHeader`` or ``None`` if the format is invalid.
            \"\"\"
            try:
                parts = dict(p.strip().split("=", 1) for p in header_value.split(","))
                return SignatureHeader(timestamp=int(parts["t"]), v1_hex=parts["v1"])
            except (ValueError, KeyError):
                return None


        def verify_signature(
            secret: str,
            body: bytes,
            header_value: str,
            now: int | None = None,
        ) -> bool:
            \"\"\"Constant-time verify with replay-window check.

            Args:
                secret: The shared signing secret.
                body: The raw request body bytes.
                header_value: The ``X-Signature`` header value to verify.
                now: Current Unix seconds override (defaults to ``time.time()``).

            Returns:
                ``True`` if the signature is valid and within the replay window.
            \"\"\"
            header = parse_signature_header(header_value)
            if header is None:
                return False
            now_ts = now if now is not None else int(time.time())
            if abs(now_ts - header.timestamp) > MAX_SIGNATURE_AGE_SECONDS:
                return False
            expected = sign_payload(secret, body, header.timestamp)
            return hmac.compare_digest(expected.v1_hex, header.v1_hex)
        """)
    dest.write_text(content)


def _write_backoff(dest: Path) -> None:
    """Write ``app/core/webhooks/backoff.py`` with the retry schedule.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Fixed exponential backoff schedule for webhook delivery retries.

        Total delivery window across 7 attempts is approximately 32 hours,
        giving partners ample time to recover from an outage without the
        sender hammering them continuously.
        \"\"\"
        from __future__ import annotations

        # Delay in seconds before each attempt (1-indexed).
        # attempt 1: immediate, attempt 2: 1s, attempt 3: 5s, …
        ATTEMPT_DELAYS_SECONDS: list[int] = [0, 1, 5, 30, 300, 3600, 21600]


        def delay_for_attempt(attempt_number: int) -> int:
            \"\"\"Return the delay in seconds before *attempt_number*.

            Args:
                attempt_number: 1-indexed attempt number.

            Returns:
                Seconds to wait before this attempt, or ``-1`` if there are no
                more retries scheduled (attempt_number exceeds the schedule).
            \"\"\"
            if attempt_number < 1 or attempt_number > len(ATTEMPT_DELAYS_SECONDS):
                return -1
            return ATTEMPT_DELAYS_SECONDS[attempt_number - 1]
        """)
    dest.write_text(content)


def _write_sender(dest: Path, max_payload_bytes: int) -> None:
    """Write ``app/core/webhooks/sender.py`` with the ``send_webhook`` helper.

    Args:
        dest: Absolute path for the new file.
        max_payload_bytes: Hard cap on payload size enforced before DB writes.
    """
    content = textwrap.dedent("""\
        \"\"\"Public helper for enqueuing outbound webhook deliveries.

        ``send_webhook`` looks up active endpoints subscribed to the event type,
        creates a ``WebhookDelivery`` row per endpoint, and enqueues an ARQ job.
        Callers never block on HTTP — the actual POST happens in the worker.
        \"\"\"
        from __future__ import annotations

        import json
        import logging
        from typing import Any
        from uuid import uuid4

        from app.core.db import async_session_maker
        from app.core.queue import get_arq_pool
        from app.crud import webhook as crud_wh

        logger = logging.getLogger(__name__)

        _MAX_PAYLOAD_BYTES = {max_bytes}


        async def send_webhook(event_type: str, payload: dict[str, Any]) -> int:
            \"\"\"Enqueue outbound webhook deliveries for *event_type*.

            Looks up all active endpoints subscribed to *event_type*, creates a
            ``WebhookDelivery`` row for each, and enqueues an ARQ ``deliver_webhook``
            job.  Returns immediately without performing any HTTP requests.

            Args:
                event_type: Logical event type string (e.g. ``item.created``).
                payload: JSON-serializable event data.

            Returns:
                Number of deliveries enqueued (0 if no subscribed endpoints).

            Raises:
                ValueError: If the serialized payload exceeds the size limit.
            \"\"\"
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            if len(body.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
                raise ValueError(
                    f"Webhook payload too large: {len(body.encode())} > {_MAX_PAYLOAD_BYTES}"
                )

            event_id = uuid4()

            async with async_session_maker() as session:
                endpoints = await crud_wh.list_endpoints_for_event(session, event_type=event_type)
                if not endpoints:
                    return 0
                deliveries = []
                for ep in endpoints:
                    delivery = await crud_wh.create_delivery(
                        session,
                        endpoint_id=ep.id,
                        event_id=event_id,
                        event_type=event_type,
                        payload=payload,
                    )
                    deliveries.append(delivery)
                await session.commit()

            pool = await get_arq_pool()
            for delivery in deliveries:
                await pool.enqueue_job("deliver_webhook", str(delivery.id))

            logger.info("Enqueued %d webhook deliveries for event_type=%s", len(deliveries), event_type)
            return len(deliveries)
        """).replace("{max_bytes}", str(max_payload_bytes))
    dest.write_text(content)


def _write_webhook_crud(dest: Path) -> None:
    """Write ``app/crud/webhook.py`` with CRUD helpers for endpoints and deliveries.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"CRUD helpers for WebhookEndpoint and WebhookDelivery models.\"\"\"
        from __future__ import annotations

        import secrets
        import uuid
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.webhook import WebhookDelivery, WebhookEndpoint
        from app.schemas.webhook import WebhookCreate, WebhookUpdate


        async def create_endpoint(
            session: AsyncSession,
            in_: WebhookCreate,
            user_id: uuid.UUID,
        ) -> WebhookEndpoint:
            \"\"\"Create a new webhook endpoint.

            Args:
                session: Async database session.
                in_: Creation input schema.
                user_id: UUID of the owning user.

            Returns:
                The persisted ``WebhookEndpoint`` instance.
            \"\"\"
            ep = WebhookEndpoint(
                url=str(in_.url),
                description=in_.description,
                events=in_.events,
                secret=secrets.token_hex(32),
                user_id=user_id,
            )
            session.add(ep)
            await session.flush()
            return ep


        async def get_endpoint(
            session: AsyncSession, *, id: uuid.UUID | str
        ) -> WebhookEndpoint | None:
            \"\"\"Fetch a single endpoint by id.

            Args:
                session: Async database session.
                id: UUID of the endpoint.

            Returns:
                The ``WebhookEndpoint`` or ``None`` if not found.
            \"\"\"
            stmt = select(WebhookEndpoint).where(WebhookEndpoint.id == id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_endpoints_for_user(
            session: AsyncSession, *, user_id: uuid.UUID
        ) -> list[WebhookEndpoint]:
            \"\"\"Return all endpoints owned by *user_id*.

            Args:
                session: Async database session.
                user_id: UUID of the owning user.

            Returns:
                List of ``WebhookEndpoint`` instances.
            \"\"\"
            stmt = select(WebhookEndpoint).where(WebhookEndpoint.user_id == user_id)
            return list((await session.execute(stmt)).scalars().all())


        async def list_endpoints_for_event(
            session: AsyncSession, *, event_type: str
        ) -> list[WebhookEndpoint]:
            \"\"\"Return active endpoints subscribed to *event_type*.

            Filters active endpoints whose ``events`` JSON list contains the
            given *event_type*.  Uses a database-agnostic approach (works with
            both PostgreSQL and SQLite).

            Args:
                session: Async database session.
                event_type: Event type string to match.

            Returns:
                List of matching active ``WebhookEndpoint`` instances.
            \"\"\"
            stmt = select(WebhookEndpoint).where(WebhookEndpoint.status == "active")
            rows = list((await session.execute(stmt)).scalars().all())
            return [ep for ep in rows if event_type in (ep.events or [])]


        async def update_endpoint(
            session: AsyncSession,
            ep: WebhookEndpoint,
            in_: WebhookUpdate,
        ) -> WebhookEndpoint:
            \"\"\"Apply partial updates to an endpoint.

            Args:
                session: Async database session.
                ep: The existing ``WebhookEndpoint`` to update.
                in_: Partial update schema (only non-None fields are applied).

            Returns:
                The updated ``WebhookEndpoint`` instance.
            \"\"\"
            data = in_.model_dump(exclude_none=True)
            for field, value in data.items():
                setattr(ep, field, value)
            await session.flush()
            return ep


        async def delete_endpoint(
            session: AsyncSession, ep: WebhookEndpoint
        ) -> None:
            \"\"\"Hard-delete an endpoint and cascade to its deliveries.

            Args:
                session: Async database session.
                ep: The ``WebhookEndpoint`` to delete.
            \"\"\"
            await session.delete(ep)
            await session.flush()


        async def create_delivery(
            session: AsyncSession,
            *,
            endpoint_id: uuid.UUID,
            event_id: uuid.UUID,
            event_type: str,
            payload: dict[str, Any],
        ) -> WebhookDelivery:
            \"\"\"Create a new delivery row for a webhook endpoint.

            Args:
                session: Async database session.
                endpoint_id: UUID of the target endpoint.
                event_id: Logical event UUID (shared across all deliveries).
                event_type: Event type string.
                payload: JSON payload dict.

            Returns:
                The persisted ``WebhookDelivery`` instance.
            \"\"\"
            delivery = WebhookDelivery(
                endpoint_id=endpoint_id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
            session.add(delivery)
            await session.flush()
            return delivery


        async def get_delivery(
            session: AsyncSession, *, id: uuid.UUID | str
        ) -> WebhookDelivery | None:
            \"\"\"Fetch a single delivery by id.

            Args:
                session: Async database session.
                id: UUID of the delivery.

            Returns:
                The ``WebhookDelivery`` or ``None`` if not found.
            \"\"\"
            stmt = select(WebhookDelivery).where(WebhookDelivery.id == id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_deliveries_for_endpoint(
            session: AsyncSession, *, endpoint_id: uuid.UUID | str
        ) -> list[WebhookDelivery]:
            \"\"\"Return all deliveries for an endpoint, newest first.

            Args:
                session: Async database session.
                endpoint_id: UUID of the endpoint.

            Returns:
                List of ``WebhookDelivery`` instances ordered by scheduled_at desc.
            \"\"\"
            stmt = (
                select(WebhookDelivery)
                .where(WebhookDelivery.endpoint_id == endpoint_id)
                .order_by(WebhookDelivery.scheduled_at.desc())
            )
            return list((await session.execute(stmt)).scalars().all())
        """)
    dest.write_text(content)


def _append_webhook_crud(dest: Path) -> None:
    """Append webhook sender CRUD helpers to an existing ``app/crud/webhook.py``.

    Called when the file already contains user-defined CRUD for a ``Webhook``
    model.  The sender functions (``create_endpoint``, ``create_delivery``, etc.)
    use unique names that do not conflict with the standard CRUD primitives
    (``create``, ``get``, ``get_multi``, ``update``, ``delete``).

    Args:
        dest: Path to the existing ``app/crud/webhook.py``.
    """
    existing = dest.read_text()
    # Guard: don't append twice
    if "create_endpoint" in existing:
        return

    block = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Outbound webhook sender CRUD — appended by add_webhook_sender tool
        # ---------------------------------------------------------------------------
        import secrets as _wh_secrets
        import uuid as _wh_uuid
        from sqlalchemy import select as _wh_select
        from sqlalchemy.ext.asyncio import AsyncSession as _wh_AS
        from app.models.webhook import WebhookDelivery, WebhookEndpoint
        from app.schemas.webhook import (
            WebhookEndpointCreate as _WHEPCreate,
            WebhookEndpointUpdate as _WHEPUpdate,
        )


        async def create_endpoint(session: _wh_AS, *, in_: _WHEPCreate, user_id: _wh_uuid.UUID) -> WebhookEndpoint:
            ep = WebhookEndpoint(
                id=_wh_uuid.uuid4(), url=str(in_.url), description=in_.description,
                events=in_.events, secret=_wh_secrets.token_hex(32), user_id=user_id,
            )
            session.add(ep)
            await session.flush()
            return ep


        async def get_endpoint(session: _wh_AS, *, id: _wh_uuid.UUID) -> WebhookEndpoint | None:
            stmt = _wh_select(WebhookEndpoint).where(WebhookEndpoint.id == id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_endpoints_for_user(session: _wh_AS, *, user_id: _wh_uuid.UUID) -> list[WebhookEndpoint]:
            stmt = _wh_select(WebhookEndpoint).where(WebhookEndpoint.user_id == user_id)
            return list((await session.execute(stmt)).scalars().all())


        async def list_endpoints_for_event(session: _wh_AS, *, event_type: str) -> list[WebhookEndpoint]:
            stmt = _wh_select(WebhookEndpoint).where(WebhookEndpoint.status == "active")
            rows = list((await session.execute(stmt)).scalars().all())
            return [ep for ep in rows if event_type in (ep.events or [])]


        async def update_endpoint(session: _wh_AS, *, ep: WebhookEndpoint, in_: _WHEPUpdate) -> WebhookEndpoint:
            for field, value in in_.model_dump(exclude_unset=True).items():
                setattr(ep, field, value)
            await session.flush()
            return ep


        async def delete_endpoint(session: _wh_AS, *, ep: WebhookEndpoint) -> None:
            await session.delete(ep)
            await session.flush()


        async def create_delivery(
            session: _wh_AS, *, endpoint_id: _wh_uuid.UUID, event_id: _wh_uuid.UUID,
            event_type: str, payload: dict,
        ) -> WebhookDelivery:
            delivery = WebhookDelivery(
                id=_wh_uuid.uuid4(), endpoint_id=endpoint_id, event_id=event_id,
                event_type=event_type, payload=payload,
            )
            session.add(delivery)
            await session.flush()
            return delivery


        async def get_delivery(session: _wh_AS, *, id: _wh_uuid.UUID) -> WebhookDelivery | None:
            stmt = _wh_select(WebhookDelivery).where(WebhookDelivery.id == id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_deliveries_for_endpoint(
            session: _wh_AS, *, endpoint_id: _wh_uuid.UUID
        ) -> list[WebhookDelivery]:
            stmt = (
                _wh_select(WebhookDelivery)
                .where(WebhookDelivery.endpoint_id == endpoint_id)
                .order_by(WebhookDelivery.scheduled_at.desc())
            )
            return list((await session.execute(stmt)).scalars().all())
        """)
    dest.write_text(existing.rstrip("\n") + "\n" + block)


def _write_webhook_schemas(dest: Path) -> None:
    """Write ``app/schemas/webhook.py`` with Pydantic schemas.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for outbound webhook endpoints and deliveries.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime
        from typing import Any

        from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


        class WebhookCreate(BaseModel):
            \"\"\"Input schema for creating a webhook endpoint.

            Attributes:
                url: Delivery URL (must be http or https).
                description: Optional human-readable note.
                events: List of event type strings to subscribe to.
            \"\"\"

            url: AnyHttpUrl
            description: str | None = None
            events: list[str] = Field(default_factory=list)


        class WebhookUpdate(BaseModel):
            \"\"\"Partial update schema for a webhook endpoint.

            All fields are optional; only supplied fields are applied.

            Attributes:
                description: New description.
                events: Replacement event list.
                status: New status (active / disabled / suspended).
            \"\"\"

            description: str | None = None
            events: list[str] | None = None
            status: str | None = None


        class WebhookEndpointPublic(BaseModel):
            \"\"\"Public representation of a webhook endpoint.

            Note: ``secret`` is intentionally excluded.  It is returned only once
            at creation time via ``WebhookEndpointCreated``.

            Attributes:
                id: UUID of the endpoint.
                url: Delivery URL.
                description: Optional description.
                events: Subscribed event type list.
                status: Endpoint status string.
                consecutive_failures: Current failure counter.
                last_success_at: UTC timestamp of last successful delivery.
                last_failure_at: UTC timestamp of last failed delivery.
                user_id: Owning user UUID.
                created_at: Creation timestamp.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            url: str
            description: str | None
            events: list[str]
            status: str
            consecutive_failures: int
            last_success_at: datetime | None
            last_failure_at: datetime | None
            user_id: uuid.UUID
            created_at: datetime


        class WebhookEndpointCreated(WebhookEndpointPublic):
            \"\"\"Extends the public schema with the signing secret.

            The ``secret`` is included exactly once — in the create response.
            Subsequent reads use ``WebhookEndpointPublic`` which omits it.

            Attributes:
                secret: HMAC signing secret for verifying delivery signatures.
            \"\"\"

            secret: str


        class WebhookDeliveryPublic(BaseModel):
            \"\"\"Public representation of a single delivery attempt.

            Attributes:
                id: UUID of the delivery record.
                endpoint_id: Parent endpoint UUID.
                event_id: Logical event UUID.
                event_type: Event type string.
                status: Delivery status (pending / succeeded / failed / dead).
                attempt_number: How many attempts have been made.
                http_status: HTTP response status from the last attempt.
                response_body: Truncated response body (max 4096 chars).
                error: Error summary string.
                scheduled_at: When the delivery was originally scheduled.
                delivered_at: UTC timestamp of successful delivery.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            endpoint_id: uuid.UUID
            event_id: uuid.UUID
            event_type: str
            status: str
            attempt_number: int
            http_status: int | None
            response_body: str | None
            error: str | None
            scheduled_at: datetime
            delivered_at: datetime | None
        """)
    dest.write_text(content)


def _append_webhook_schemas(dest: Path) -> None:
    """Append webhook sender Pydantic schemas to an existing ``app/schemas/webhook.py``.

    Called when the file already contains user-defined schemas for a ``Webhook``
    model.  The new ``WebhookEndpoint*`` and ``WebhookDelivery*`` schemas are
    appended without modifying the existing content.

    Args:
        dest: Path to the existing ``app/schemas/webhook.py``.
    """
    existing = dest.read_text()
    if "WebhookEndpointCreate" in existing:
        return

    block = textwrap.dedent("""\

        # ---------------------------------------------------------------------------
        # Outbound webhook sender schemas — appended by add_webhook_sender tool
        # ---------------------------------------------------------------------------
        import uuid as _wh_uuid
        from datetime import datetime as _wh_datetime
        from typing import Any as _wh_Any
        from pydantic import AnyHttpUrl as _wh_AnyHttpUrl, BaseModel as _wh_BM, Field as _wh_Field


        class WebhookEndpointCreate(_wh_BM):
            \"\"\"Create a new webhook endpoint.\"\"\"
            url: _wh_AnyHttpUrl
            description: str | None = None
            events: list[str] = _wh_Field(default_factory=list)


        class WebhookEndpointUpdate(_wh_BM):
            \"\"\"Partial update for a webhook endpoint.\"\"\"
            url: _wh_AnyHttpUrl | None = None
            description: str | None = None
            events: list[str] | None = None
            status: str | None = None


        class WebhookEndpointPublic(_wh_BM):
            \"\"\"Public view of a webhook endpoint (secret excluded).\"\"\"
            model_config = {"from_attributes": True}
            id: _wh_uuid.UUID
            url: str
            description: str | None
            events: list[str]
            status: str
            user_id: _wh_uuid.UUID
            created_at: _wh_datetime


        class WebhookEndpointWithSecret(WebhookEndpointPublic):
            \"\"\"Returned once at creation — includes the signing secret.\"\"\"
            secret: str


        class WebhookDeliveryPublic(_wh_BM):
            \"\"\"Public view of a single delivery attempt.\"\"\"
            model_config = {"from_attributes": True}
            id: _wh_uuid.UUID
            endpoint_id: _wh_uuid.UUID
            event_id: _wh_uuid.UUID
            event_type: str
            status: str
            attempt_number: int
            http_status: int | None
            response_body: str | None
            error: str | None
            scheduled_at: _wh_datetime | None
            delivered_at: _wh_datetime | None
        """)
    dest.write_text(existing.rstrip("\n") + "\n" + block)


def _write_webhook_worker(
    dest: Path,
    http_timeout_seconds: float,
    disable_after_consecutive_failures: int,
) -> None:
    """Write ``app/workers/webhook_worker.py`` with the ARQ ``deliver_webhook`` task.

    Args:
        dest: Absolute path for the new file.
        http_timeout_seconds: Per-request HTTP timeout.
        disable_after_consecutive_failures: Endpoint auto-disable threshold.
    """
    content = textwrap.dedent("""\
        \"\"\"ARQ worker for outbound webhook delivery.

        ``deliver_webhook`` loads the delivery row, attempts an HTTP POST with
        an HMAC-signed body, persists the outcome, and enqueues a retry if the
        attempt failed and there are remaining schedule slots.

        Endpoints with too many consecutive failures are auto-disabled.
        \"\"\"
        from __future__ import annotations

        import json
        import logging
        from datetime import datetime, timezone

        import httpx
        from arq.connections import RedisSettings

        from app.core.db import async_session_maker
        from app.core.webhooks.backoff import delay_for_attempt
        from app.core.webhooks.signer import sign_payload
        from app.crud import webhook as crud_wh

        logger = logging.getLogger(__name__)

        _HTTP_TIMEOUT = {timeout}
        _DISABLE_AFTER = {disable}


        async def _attempt_delivery(delivery: object, endpoint: object) -> None:
            \"\"\"Perform one HTTP POST attempt and record the outcome on ``delivery``.

            Args:
                delivery: The ``WebhookDelivery`` ORM row being processed.
                endpoint: The parent ``WebhookEndpoint`` ORM row.
            \"\"\"
            delivery.attempt_number += 1  # type: ignore[attr-defined]
            body_bytes = json.dumps(
                delivery.payload, separators=(",", ":"), sort_keys=True  # type: ignore[attr-defined]
            ).encode("utf-8")
            sig_header = sign_payload(endpoint.secret, body_bytes).to_header_value()  # type: ignore[attr-defined]
            headers = {
                "Content-Type": "application/json",
                "X-Signature": sig_header,
                "X-Event-Id": str(delivery.event_id),  # type: ignore[attr-defined]
                "X-Event-Type": delivery.event_type,  # type: ignore[attr-defined]
                "X-Attempt": str(delivery.attempt_number),  # type: ignore[attr-defined]
            }
            try:
                async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                    resp = await client.post(endpoint.url, content=body_bytes, headers=headers)  # type: ignore[attr-defined]
                delivery.http_status = resp.status_code  # type: ignore[attr-defined]
                delivery.response_body = resp.text[:4096]  # type: ignore[attr-defined]
                if 200 <= resp.status_code < 300:
                    delivery.status = "succeeded"  # type: ignore[attr-defined]
                    delivery.delivered_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]
                    endpoint.last_success_at = delivery.delivered_at  # type: ignore[attr-defined]
                    endpoint.consecutive_failures = 0  # type: ignore[attr-defined]
                else:
                    _mark_failure(delivery, endpoint, f"HTTP {resp.status_code}")
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                _mark_failure(delivery, endpoint, repr(exc)[:500])


        async def deliver_webhook(ctx: dict, delivery_id: str) -> None:
            \"\"\"ARQ task: attempt delivery, persist outcome, retry if needed.

            Args:
                ctx: ARQ context dict (contains ``redis`` key for enqueuing retries).
                delivery_id: UUID string of the ``WebhookDelivery`` row to process.
            \"\"\"
            async with async_session_maker() as session:
                delivery = await crud_wh.get_delivery(session, id=delivery_id)
                if not delivery or delivery.status not in ("pending",):
                    return
                endpoint = await crud_wh.get_endpoint(session, id=delivery.endpoint_id)
                if not endpoint or endpoint.status != "active":
                    delivery.status = "dead"
                    await session.commit()
                    return

                await _attempt_delivery(delivery, endpoint)
                await session.commit()

            if delivery.status == "pending":
                next_delay = delay_for_attempt(delivery.attempt_number + 1)
                if next_delay >= 0:
                    await ctx["redis"].enqueue_job(
                        "deliver_webhook",
                        str(delivery.id),
                        _defer_by=next_delay,
                    )


        def _mark_failure(delivery: object, endpoint: object, error: str) -> None:
            \"\"\"Update delivery and endpoint fields after a failed attempt.

            Args:
                delivery: The ``WebhookDelivery`` ORM instance.
                endpoint: The parent ``WebhookEndpoint`` ORM instance.
                error: Short error description string.
            \"\"\"
            delivery.error = error[:500]  # type: ignore[attr-defined]
            endpoint.consecutive_failures += 1  # type: ignore[attr-defined]
            endpoint.last_failure_at = datetime.now(timezone.utc)  # type: ignore[attr-defined]

            from app.core.config import settings as _settings
            max_attempts = getattr(_settings, "WEBHOOK_MAX_ATTEMPTS", 7)
            if delivery.attempt_number >= max_attempts:  # type: ignore[attr-defined]
                delivery.status = "dead"  # type: ignore[attr-defined]
            else:
                delivery.status = "pending"  # type: ignore[attr-defined]

            if endpoint.consecutive_failures >= _DISABLE_AFTER:  # type: ignore[attr-defined]
                endpoint.status = "disabled"  # type: ignore[attr-defined]
                delivery.status = "dead"  # type: ignore[attr-defined]


        class WorkerSettings:
            \"\"\"ARQ worker configuration.

            Register this class when starting the worker::

                arq app.workers.webhook_worker.WorkerSettings
            \"\"\"

            functions = [deliver_webhook]
            job_timeout = _HTTP_TIMEOUT + 5
            max_jobs = 100

            @staticmethod
            def redis_settings() -> RedisSettings:
                \"\"\"Build Redis settings from the application config.

                Returns:
                    ARQ ``RedisSettings`` for the configured ``REDIS_URL``.
                \"\"\"
                from app.core.config import settings as _settings
                return RedisSettings.from_dsn(getattr(_settings, "REDIS_URL", "redis://localhost"))
        """).replace("{timeout}", str(http_timeout_seconds)).replace("{disable}", str(disable_after_consecutive_failures))
    dest.write_text(content)


def _write_webhook_routes(dest: Path) -> None:
    """Write ``app/api/routes/webhooks.py`` with admin CRUD endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Admin routes for managing outbound webhook endpoints.\"\"\"
        from __future__ import annotations

        import uuid

        from fastapi import APIRouter, HTTPException, status

        from app.api.deps import CurrentUser, SessionDep
        from app.crud import webhook as crud_wh
        from app.schemas.webhook import (
            WebhookCreate,
            WebhookDeliveryPublic,
            WebhookEndpointCreated,
            WebhookEndpointPublic,
            WebhookUpdate,
        )

        router = APIRouter(prefix="/webhooks", tags=["webhooks"])


        @router.post("/", response_model=WebhookEndpointCreated, status_code=status.HTTP_201_CREATED)
        async def create_webhook(
            in_: WebhookCreate,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> WebhookEndpointCreated:
            \"\"\"Register a new webhook endpoint.  Returns the signing secret once.

            Args:
                in_: Creation input (url, events, optional description).
                session: Injected async DB session.
                current_user: Authenticated requesting user.

            Returns:
                The created endpoint including the signing secret.
            \"\"\"
            ep = await crud_wh.create_endpoint(session, in_=in_, user_id=current_user.id)
            await session.commit()
            await session.refresh(ep)
            return WebhookEndpointCreated.model_validate(ep)


        @router.get("/", response_model=list[WebhookEndpointPublic])
        async def list_my_webhooks(
            session: SessionDep,
            current_user: CurrentUser,
        ) -> list[WebhookEndpointPublic]:
            \"\"\"List all webhook endpoints owned by the current user.

            Args:
                session: Injected async DB session.
                current_user: Authenticated requesting user.

            Returns:
                List of endpoint summaries (secret excluded).
            \"\"\"
            return await crud_wh.list_endpoints_for_user(session, user_id=current_user.id)


        @router.patch("/{webhook_id}", response_model=WebhookEndpointPublic)
        async def update_webhook(
            webhook_id: uuid.UUID,
            in_: WebhookUpdate,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> WebhookEndpointPublic:
            \"\"\"Update a webhook endpoint.  Ownership is verified.

            Args:
                webhook_id: UUID of the endpoint to update.
                in_: Partial update data.
                session: Injected async DB session.
                current_user: Authenticated requesting user.

            Raises:
                HTTPException: 404 if not found or not owned by the current user.

            Returns:
                Updated endpoint summary.
            \"\"\"
            ep = await crud_wh.get_endpoint(session, id=webhook_id)
            if not ep or ep.user_id != current_user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            ep = await crud_wh.update_endpoint(session, ep=ep, in_=in_)
            await session.commit()
            await session.refresh(ep)
            return WebhookEndpointPublic.model_validate(ep)


        @router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
        async def delete_webhook(
            webhook_id: uuid.UUID,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> None:
            \"\"\"Delete a webhook endpoint.  Ownership is verified.

            Args:
                webhook_id: UUID of the endpoint to delete.
                session: Injected async DB session.
                current_user: Authenticated requesting user.

            Raises:
                HTTPException: 404 if not found or not owned by the current user.
            \"\"\"
            ep = await crud_wh.get_endpoint(session, id=webhook_id)
            if not ep or ep.user_id != current_user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            await crud_wh.delete_endpoint(session, ep=ep)
            await session.commit()


        @router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryPublic])
        async def list_deliveries(
            webhook_id: uuid.UUID,
            session: SessionDep,
            current_user: CurrentUser,
        ) -> list[WebhookDeliveryPublic]:
            \"\"\"List delivery attempts for a webhook endpoint.

            Args:
                webhook_id: UUID of the endpoint.
                session: Injected async DB session.
                current_user: Authenticated requesting user.

            Raises:
                HTTPException: 404 if not found or not owned by the current user.

            Returns:
                List of delivery records, newest first.
            \"\"\"
            ep = await crud_wh.get_endpoint(session, id=webhook_id)
            if not ep or ep.user_id != current_user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return await crud_wh.list_deliveries_for_endpoint(session, endpoint_id=webhook_id)
        """)
    dest.write_text(content)


def _write_webhook_migration(versions_dir: Path) -> Path:
    """Generate ``alembic/versions/0015_add_webhook_sender.py``.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = textwrap.dedent("""\
        \"\"\"Add webhook_endpoints and webhook_deliveries tables.

        Revision ID: 0015_add_webhook_sender
        Revises: {down_rev}
        Create Date: auto-generated by add_webhook_sender tool
        \"\"\"
        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0015_add_webhook_sender"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create webhook_endpoints and webhook_deliveries tables.\"\"\"
            op.create_table(
                "webhook_endpoints",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column("url", sa.String(2048), nullable=False),
                sa.Column("description", sa.String(500), nullable=True),
                sa.Column("events", sa.JSON(), server_default="[]", nullable=False),
                sa.Column("secret", sa.String(128), nullable=False),
                sa.Column("status", sa.String(16), server_default="active", nullable=False),
                sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
                sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column(
                    "user_id",
                    sa.Uuid(),
                    sa.ForeignKey("users.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.CheckConstraint(
                    "status IN ('active','disabled','suspended')",
                    name="ck_webhook_endpoints_status",
                ),
                sa.CheckConstraint(
                    "url LIKE 'http://%' OR url LIKE 'https://%'",
                    name="ck_webhook_endpoints_url_format",
                ),
            )
            op.create_index("ix_webhook_endpoints_user_id", "webhook_endpoints", ["user_id"])
            op.create_table(
                "webhook_deliveries",
                sa.Column("id", sa.Uuid(), primary_key=True),
                sa.Column(
                    "endpoint_id",
                    sa.Uuid(),
                    sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
                    nullable=False,
                ),
                sa.Column("event_id", sa.Uuid(), nullable=False),
                sa.Column("event_type", sa.String(127), nullable=False),
                sa.Column("payload", sa.JSON(), nullable=False),
                sa.Column("status", sa.String(16), server_default="pending", nullable=False),
                sa.Column("attempt_number", sa.Integer(), server_default="0", nullable=False),
                sa.Column("http_status", sa.Integer(), nullable=True),
                sa.Column("response_body", sa.String(4096), nullable=True),
                sa.Column("error", sa.String(500), nullable=True),
                sa.Column(
                    "scheduled_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
                sa.CheckConstraint(
                    "status IN ('pending','succeeded','failed','dead')",
                    name="ck_webhook_deliveries_status",
                ),
            )
            op.create_index(
                "ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"]
            )
            op.create_index(
                "ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"]
            )


        def downgrade() -> None:
            \"\"\"Drop webhook tables and indexes.\"\"\"
            op.drop_index("ix_webhook_deliveries_event_id", "webhook_deliveries")
            op.drop_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries")
            op.drop_table("webhook_deliveries")
            op.drop_index("ix_webhook_endpoints_user_id", "webhook_endpoints")
            op.drop_table("webhook_endpoints")
        """).format(down_rev=down_rev)
    migration_file = versions_dir / "0015_add_webhook_sender.py"
    migration_file.write_text(content)
    return migration_file


def _patch_config(
    config_file: Path,
    max_attempts: int,
    http_timeout_seconds: float,
    max_payload_bytes: int,
    disable_after_consecutive_failures: int,
) -> None:
    """Inject webhook sender settings into ``app/core/config.py``.

    Args:
        config_file: Path to the existing config module.
        max_attempts: Max delivery attempts.
        http_timeout_seconds: HTTP timeout.
        max_payload_bytes: Payload size cap.
        disable_after_consecutive_failures: Auto-disable threshold.
    """
    src = config_file.read_text()
    if "WEBHOOK_MAX_ATTEMPTS" in src:
        return

    snippet = textwrap.dedent("""\

        # --- Webhook sender settings — added by add_webhook_sender tool ---
        WEBHOOK_MAX_ATTEMPTS: int = {max_att}
        WEBHOOK_HTTP_TIMEOUT_SECONDS: float = {timeout}
        WEBHOOK_MAX_PAYLOAD_BYTES: int = {max_bytes}
        WEBHOOK_DISABLE_AFTER_FAILURES: int = {disable}
        """).replace("{max_att}", str(max_attempts)) \
           .replace("{timeout}", str(http_timeout_seconds)) \
           .replace("{max_bytes}", str(max_payload_bytes)) \
           .replace("{disable}", str(disable_after_consecutive_failures))

    config_file.write_text(src.rstrip("\n") + snippet + "\n")


def _patch_api_main(routes_init: Path) -> None:
    """Register the webhooks router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.webhooks import router as webhooks_router",
        include_line="api_router.include_router(webhooks_router)",
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
        import_line: Import statement to insert (no trailing newline).
        include_line: ``api_router.include_router(...)`` call (no trailing newline).
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


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the Python file to validate.

    Raises:
        SyntaxError: If the file contains a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(f"Generated file {path} has a syntax error: {exc}") from exc


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
