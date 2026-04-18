"""TOOL-016: add_webhook_receiver — add inbound webhook handling to a FastAPI project.

Creates the ``InboundVerifier`` ABC, provider implementations (Stripe, GitHub,
internal HMAC), an idempotency cache (Redis SET NX), a handler registry with
``@webhook_handler`` decorator, a persistence model, CRUD helpers, the receive
endpoint, an ARQ background dispatcher, Pydantic schemas, and an Alembic
migration.

Security guarantees:
* Every request is HMAC-verified before any DB write.
* Duplicate deliveries are absorbed by Redis SET NX (fast path) AND a DB unique
  constraint (durable fallback).
* Timestamp replay attacks are blocked by per-provider tolerance windows.
* Body size is capped BEFORE verification to prevent DoS amplification.

The tool is idempotent: a second run detects the ``InboundWebhook`` model
fingerprint and returns ``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.realtime.add_webhook_receiver import add_webhook_receiver

    result = add_webhook_receiver(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/models/webhook_inbound.py", …]
    print(result.next_steps)    # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path
from typing import Literal

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


MCP_TOOL = {
    "name": "fastapi_add_webhook_receiver",
    "description": "Add inbound webhook receiver with signature verification and idempotency.",
    "tags": ["extend", "realtime"],
    "entry": "add_webhook_receiver",
}



# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_webhook_receiver(
    inp: ToolInput,
    *,
    providers: list[Literal["stripe", "github", "internal"]] | None = None,
    idempotency_ttl_seconds: int = 86400,
    signature_tolerance_seconds: int = 300,
    max_payload_bytes: int = 1_048_576,
) -> ToolResult:
    """Add inbound webhook handling to a FastAPI project.

    Creates the verifier ABC, provider implementations, idempotency cache,
    handler registry, model, CRUD, routes, ARQ worker, schemas, and migration.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        providers: Provider verifiers to enable.  Defaults to all three
            (``["stripe", "github", "internal"]``).
        idempotency_ttl_seconds: How long event IDs stay deduped in Redis
            (default 86400 = 24 hours).
        signature_tolerance_seconds: Clock-skew tolerance for signed timestamps
            (default 300 = 5 minutes).
        max_payload_bytes: Hard cap on incoming body size (default 1 MiB).

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
    enabled_providers = providers or ["stripe", "github", "internal"]

    # --- Pre-flight: already installed? ------------------------------------
    model_file = app_dir / "models" / "webhook_inbound.py"
    if model_file.exists() and "InboundWebhook" in model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=["InboundWebhook already present — webhook receiver is already enabled, skipped."],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create InboundWebhook model, verifier ABC, provider impls,",
                f"         registry, idempotency cache, routes, ARQ worker, schemas, migration.",
                f"         Providers: {enabled_providers}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 – model
    has_tenants = (app_dir / "models" / "tenant.py").exists()
    _write_inbound_model(model_file, has_tenants=has_tenants)
    files_created.append(str(model_file))

    # Register InboundWebhook in app/models/__init__.py for metadata.create_all().
    _patch_models_init(
        app_dir / "models" / "__init__.py",
        [("webhook_inbound", "InboundWebhook")],
    )

    # Step 2 – verifier ABC + providers
    inbound_core_dir = app_dir / "core" / "inbound_webhooks"
    providers_dir = inbound_core_dir / "providers"
    providers_dir.mkdir(parents=True, exist_ok=True)

    init_core = inbound_core_dir / "__init__.py"
    if not init_core.exists():
        init_core.write_text('"""Inbound webhooks sub-package."""\n')
        files_created.append(str(init_core))

    init_prov = providers_dir / "__init__.py"
    if not init_prov.exists():
        init_prov.write_text('"""Provider verifier implementations."""\n')
        files_created.append(str(init_prov))

    base_file = inbound_core_dir / "base.py"
    _write_verifier_base(base_file)
    files_created.append(str(base_file))

    for provider in enabled_providers:
        prov_file = providers_dir / f"{provider}.py"
        _write_provider(prov_file, provider, signature_tolerance_seconds)
        files_created.append(str(prov_file))

    # Step 3 – registry
    registry_file = inbound_core_dir / "registry.py"
    _write_registry(registry_file, enabled_providers)
    files_created.append(str(registry_file))

    # Step 4 – idempotency cache
    idempotency_file = inbound_core_dir / "idempotency.py"
    _write_idempotency(idempotency_file, idempotency_ttl_seconds)
    files_created.append(str(idempotency_file))

    # Step 5 – CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    crud_file = crud_dir / "inbound_webhook.py"
    _write_inbound_crud(crud_file)
    files_created.append(str(crud_file))

    # Step 6 – schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    schema_file = schemas_dir / "inbound_webhook.py"
    _write_inbound_schemas(schema_file)
    files_created.append(str(schema_file))

    # Step 7 – ARQ worker
    workers_dir = app_dir / "workers"
    workers_dir.mkdir(parents=True, exist_ok=True)
    worker_init = workers_dir / "__init__.py"
    if not worker_init.exists():
        worker_init.write_text('"""Background workers sub-package."""\n')
        files_created.append(str(worker_init))
    worker_file = workers_dir / "inbound_webhook_worker.py"
    _write_inbound_worker(worker_file)
    files_created.append(str(worker_file))

    # Step 8 – routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    route_file = routes_dir / "inbound_webhooks.py"
    _write_inbound_routes(route_file, max_payload_bytes)
    files_created.append(str(route_file))

    # Step 9 – migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_inbound_migration(versions_dir, has_tenants=has_tenants)
        files_created.append(str(migration_file))

    # Step 10 – patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(
            config_file,
            idempotency_ttl_seconds,
            signature_tolerance_seconds,
            max_payload_bytes,
            enabled_providers,
        )
        files_modified.append(str(config_file))

    # Step 11 – register inbound_webhooks router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_api_main(routes_init)
        files_modified.append(str(routes_init))

    # Step 12 – ensure app/core/redis.py exists (base project may not have it)
    redis_module = app_dir / "core" / "redis.py"
    if not redis_module.exists():
        _write_redis_module(redis_module)
        files_created.append(str(redis_module))

    # Step 12b – ensure app/core/queue.py exists (provides get_arq_pool)
    queue_module = app_dir / "core" / "queue.py"
    if not queue_module.exists():
        _write_queue_module(queue_module)
        files_created.append(str(queue_module))

    # Step 13 – add redis to requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate
    for path_str in files_created:
        _assert_parses(Path(path_str))

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            f"Inbound webhook receiver added: providers={enabled_providers}.",
            f"Idempotency TTL: {idempotency_ttl_seconds}s.  "
            f"Signature tolerance: {signature_tolerance_seconds}s.",
            f"Payload cap: {max_payload_bytes} bytes.",
            "Receive endpoint: POST /webhooks/incoming/{provider}.",
            "Register handlers with: @webhook_handler('stripe', 'event.type').",
        ],
        next_steps=[
            "alembic upgrade head",
            "Set provider secrets in .env: STRIPE_WEBHOOK_SECRET, "
            "GITHUB_WEBHOOK_SECRET, INTERNAL_WEBHOOK_SECRET.",
            "Set REDIS_URL in .env — idempotency cache requires Redis.",
            "Run the ARQ worker: arq app.workers.inbound_webhook_worker.WorkerSettings",
            "Restart the application so the inbound webhooks router is active.",
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


def _write_inbound_model(dest: Path, *, has_tenants: bool = False) -> None:
    """Write ``app/models/webhook_inbound.py`` with ``InboundWebhook``.

    Args:
        dest: Absolute path for the new file.
        has_tenants: Whether ``app/models/tenant.py`` exists.  When *True* the
            ``tenant_id`` column includes a ``ForeignKey("tenants.id")``
            reference; otherwise it is a plain nullable UUID column (no FK).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)

    if has_tenants:
        fk_import = "ForeignKey,\n        "
        tenant_id_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        ForeignKey("tenants.id", ondelete="SET NULL"),\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant context for multi-tenant webhook routing",\n'
            '    )'
        )
    else:
        fk_import = ""
        tenant_id_col = (
            '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
            '        Uuid,\n'
            '        nullable=True,\n'
            '        index=True,\n'
            '        comment="Tenant context for multi-tenant webhook routing",\n'
            '    )'
        )

    content = textwrap.dedent("""\
        \"\"\"SQLAlchemy model for inbound webhook event records.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from sqlalchemy import (
            JSON,
            CheckConstraint,
            DateTime,
            {fk_import}String,
            UniqueConstraint,
            Uuid,
            func,
        )
        from sqlalchemy.orm import Mapped, mapped_column

        from app.models.base import Base


        class InboundWebhook(Base):
            \"\"\"Audit record for a single received webhook event.

            One row is written per received event, including duplicates
            (marked with status='duplicate' for visibility).

            Attributes:
                id: UUID primary key.
                tenant_id: Tenant UUID for multi-tenant context propagation.
                provider: Provider name (stripe / github / internal).
                provider_event_id: Provider-assigned event id for deduplication.
                event_type: Provider event type string.
                payload: Full JSON event payload.
                raw_headers: Lowercased request headers at time of receipt.
                status: received / processing / succeeded / failed / duplicate.
                error: Error summary (max 500 chars).
                received_at: UTC timestamp when the request arrived.
                processed_at: UTC timestamp when the handler completed.
            \"\"\"

            __tablename__ = "inbound_webhooks"

            id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
            TENANT_ID_PLACEHOLDER
            provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
            provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
            event_type: Mapped[str] = mapped_column(String(127), nullable=False)
            payload: Mapped[dict] = mapped_column(JSON, nullable=False)
            raw_headers: Mapped[dict] = mapped_column(JSON, nullable=False)
            status: Mapped[str] = mapped_column(
                String(16), nullable=False, server_default="received"
            )
            error: Mapped[str | None] = mapped_column(String(500), nullable=True)
            received_at: Mapped[datetime] = mapped_column(
                DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
            )
            processed_at: Mapped[datetime | None] = mapped_column(
                DateTime(timezone=True), nullable=True
            )

            __table_args__ = (
                UniqueConstraint(
                    "provider",
                    "provider_event_id",
                    name="uq_inbound_webhook_event",
                ),
                CheckConstraint(
                    "status IN ('received','processing','succeeded','failed','duplicate')",
                    name="ck_inbound_webhooks_status",
                ),
            )
        """).replace("{fk_import}", fk_import).replace(
        "    TENANT_ID_PLACEHOLDER", tenant_id_col,
    )
    dest.write_text(content)


def _write_verifier_base(dest: Path) -> None:
    """Write ``app/core/inbound_webhooks/base.py`` with the ABC and ``VerifiedEvent``.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Abstract base class and value objects for inbound webhook verifiers.\"\"\"
        from __future__ import annotations

        from abc import ABC, abstractmethod
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class VerifiedEvent:
            \"\"\"Value object returned by a successful verification.

            Attributes:
                provider: Provider name string (e.g. ``"stripe"``).
                event_id: Provider-assigned event identifier.
                event_type: Provider event type string.
                payload: Parsed JSON event payload dict.
            \"\"\"

            provider: str
            event_id: str
            event_type: str
            payload: dict


        class InboundVerifier(ABC):
            \"\"\"Abstract base class for provider-specific webhook verifiers.

            Subclasses must set the ``name`` class attribute and implement
            ``verify``.  The ``verify`` method must raise ``HTTPException``
            on any signature, format, or replay error — it MUST NOT return
            ``None`` or swallow exceptions silently.
            \"\"\"

            name: str

            @abstractmethod
            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                \"\"\"Verify the inbound request and return a ``VerifiedEvent``.

                Args:
                    body: Raw request body bytes.
                    headers: Lowercased request headers dict.

                Returns:
                    A ``VerifiedEvent`` on successful verification.

                Raises:
                    HTTPException(400): On signature mismatch or invalid format.
                    HTTPException(401): On missing required authentication header.
                \"\"\"
        """)
    dest.write_text(content)


def _write_provider(dest: Path, provider: str, tolerance: int) -> None:
    """Write a provider-specific verifier implementation.

    Args:
        dest: Absolute path for the new file.
        provider: Provider name (``"stripe"``, ``"github"``, or ``"internal"``).
        tolerance: Signature timestamp tolerance in seconds.
    """
    writers = {
        "stripe": _write_stripe_verifier,
        "github": _write_github_verifier,
        "internal": _write_internal_verifier,
    }
    writers[provider](dest, tolerance)


def _write_stripe_verifier(dest: Path, tolerance: int) -> None:
    """Write ``app/core/inbound_webhooks/providers/stripe.py``.

    Args:
        dest: Absolute path for the new file.
        tolerance: Signature timestamp tolerance in seconds.
    """
    content = textwrap.dedent("""\
        \"\"\"Stripe webhook signature verifier.

        Validates the ``Stripe-Signature: t=...,v1=...`` header using HMAC-SHA256
        over ``f\"{ts}.{body}\"``, rejects stale timestamps, and uses
        ``hmac.compare_digest`` to prevent timing-oracle attacks.
        \"\"\"
        from __future__ import annotations

        import hashlib
        import hmac
        import json
        import time

        from fastapi import HTTPException

        from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent

        _TOLERANCE = {tol}


        class StripeVerifier(InboundVerifier):
            \"\"\"Verify Stripe webhook payloads using the ``Stripe-Signature`` header.\"\"\"

            name = "stripe"

            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                \"\"\"Verify a Stripe-signed webhook request.

                Raises:
                    HTTPException(401): If ``stripe-signature`` header is missing.
                    HTTPException(400): If the timestamp is out of tolerance or the
                        HMAC does not match.
                \"\"\"
                sig_header = headers.get("stripe-signature")
                if not sig_header:
                    raise HTTPException(401, "Missing Stripe-Signature header")
                parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
                try:
                    ts = int(parts.get("t", 0))
                except ValueError:
                    raise HTTPException(400, "Invalid Stripe signature timestamp")
                if abs(int(time.time()) - ts) > _TOLERANCE:
                    raise HTTPException(400, "Stripe signature timestamp out of tolerance")

                from app.core.config import settings as _settings
                secret = getattr(_settings, "STRIPE_WEBHOOK_SECRET", "")
                signed_payload = f"{ts}.".encode("ascii") + body
                expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
                if not hmac.compare_digest(expected, parts.get("v1", "")):
                    raise HTTPException(400, "Stripe signature mismatch")
                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    raise HTTPException(400, "Invalid JSON body")
                return VerifiedEvent(
                    provider="stripe",
                    event_id=event.get("id", ""),
                    event_type=event.get("type", "unknown"),
                    payload=event,
                )
        """).replace("{tol}", str(tolerance))
    dest.write_text(content)


def _write_github_verifier(dest: Path, _tolerance: int) -> None:
    """Write ``app/core/inbound_webhooks/providers/github.py``.

    Args:
        dest: Absolute path for the new file.
        _tolerance: Unused (GitHub does not include a timestamp).
    """
    content = textwrap.dedent("""\
        \"\"\"GitHub webhook signature verifier.

        Validates the ``X-Hub-Signature-256: sha256=<hex>`` header using
        HMAC-SHA256 over the raw body, and uses ``hmac.compare_digest`` to
        prevent timing-oracle attacks.  GitHub does not include a timestamp so
        replay protection is the caller's responsibility (use idempotency cache).
        \"\"\"
        from __future__ import annotations

        import hashlib
        import hmac
        import json

        from fastapi import HTTPException

        from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent


        class GitHubVerifier(InboundVerifier):
            \"\"\"Verify GitHub webhook payloads using ``X-Hub-Signature-256``.\"\"\"

            name = "github"

            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                \"\"\"Verify a GitHub-signed webhook request.

                Args:
                    body: Raw request body bytes.
                    headers: Lowercased request headers dict.

                Returns:
                    A ``VerifiedEvent`` containing the parsed GitHub event.

                Raises:
                    HTTPException(401): If the signature or delivery-id header is absent.
                    HTTPException(400): If the HMAC does not match or the body is invalid JSON.
                \"\"\"
                sig_header = headers.get("x-hub-signature-256", "")
                if not sig_header or not sig_header.startswith("sha256="):
                    raise HTTPException(401, "Missing X-Hub-Signature-256 header")

                from app.core.config import settings as _settings
                secret = getattr(_settings, "GITHUB_WEBHOOK_SECRET", "")
                expected = hmac.new(
                    secret.encode("utf-8"), body, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(f"sha256={expected}", sig_header):
                    raise HTTPException(400, "GitHub signature mismatch")

                try:
                    event = json.loads(body)
                except json.JSONDecodeError:
                    raise HTTPException(400, "Invalid JSON body")

                delivery_id = headers.get("x-github-delivery")
                if not delivery_id:
                    raise HTTPException(400, "Missing X-GitHub-Delivery header")
                event_type = headers.get("x-github-event", "unknown")

                return VerifiedEvent(
                    provider="github",
                    event_id=delivery_id,
                    event_type=event_type,
                    payload=event,
                )
        """)
    dest.write_text(content)


def _write_internal_verifier(dest: Path, tolerance: int) -> None:
    """Write ``app/core/inbound_webhooks/providers/internal.py``.

    Args:
        dest: Absolute path for the new file.
        tolerance: Unused here (signature module handles tolerance internally).
    """
    content = textwrap.dedent("""\
        \"\"\"Internal webhook verifier.

        Reuses the ``verify_signature`` helper from ``add_webhook_sender`` for
        exact symmetry with outbound deliveries.  The ``X-Signature`` header
        format is ``t=<unix_seconds>,v1=<hex-hmac-sha256>``.
        \"\"\"
        from __future__ import annotations

        import json

        from fastapi import HTTPException

        from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent


        class InternalVerifier(InboundVerifier):
            \"\"\"Verify internal (sister-service) webhook payloads.\"\"\"

            name = "internal"

            @staticmethod
            def _check_hmac_signature(secret: str, body: bytes, sig: str) -> None:
                \"\"\"Verify an inline HMAC-SHA256 ``t=<ts>,v1=<hex>`` signature.

                Args:
                    secret: Shared HMAC secret string.
                    body: Raw request body bytes.
                    sig: Raw ``X-Signature`` header value.

                Raises:
                    HTTPException(400): Invalid timestamp, timestamp drift > 300 s, or mismatch.
                \"\"\"
                import hashlib
                import hmac
                import time
                parts = dict(p.split("=", 1) for p in sig.split(",") if "=" in p)
                try:
                    ts = int(parts.get("t", 0))
                except ValueError:
                    raise HTTPException(400, "Invalid X-Signature timestamp")
                if abs(int(time.time()) - ts) > 300:
                    raise HTTPException(400, "X-Signature timestamp out of tolerance")
                expected = hmac.new(
                    secret.encode("utf-8"), f"{ts}.".encode("utf-8") + body, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(expected, parts.get("v1", "")):
                    raise HTTPException(400, "Internal signature mismatch")


            def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
                \"\"\"Verify an internally-signed webhook request.

                Args:
                    body: Raw request body bytes.
                    headers: Lowercased request headers dict.

                Returns:
                    A ``VerifiedEvent`` with the parsed payload.

                Raises:
                    HTTPException(401): If the ``x-signature`` header is missing.
                    HTTPException(400): If signature invalid or body is invalid JSON.
                \"\"\"
                sig = headers.get("x-signature")
                if not sig:
                    raise HTTPException(401, "Missing X-Signature header")
                from app.core.config import settings as _settings
                secret = getattr(_settings, "INTERNAL_WEBHOOK_SECRET", "")
                try:
                    from app.core.webhooks.signer import verify_signature
                    if not verify_signature(secret, body, sig):
                        raise HTTPException(400, "Internal signature mismatch")
                except ImportError:
                    self._check_hmac_signature(secret, body, sig)
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    raise HTTPException(400, "Invalid JSON body")
                event_id = headers.get("x-event-id")
                if not event_id:
                    raise HTTPException(400, "Missing X-Event-Id header")
                return VerifiedEvent(
                    provider="internal", event_id=event_id,
                    event_type=headers.get("x-event-type", "unknown"), payload=payload,
                )
        """)
    dest.write_text(content)


def _write_registry(dest: Path, enabled_providers: list[str]) -> None:
    """Write ``app/core/inbound_webhooks/registry.py`` with verifier + handler registry.

    Args:
        dest: Absolute path for the new file.
        enabled_providers: List of provider names to pre-register.
    """
    # Map provider names to their exact class names (must match _write_provider output)
    _verifier_class = {
        "stripe": "StripeVerifier",
        "github": "GitHubVerifier",
        "internal": "InternalVerifier",
    }
    import_lines = "\n".join(
        f"from app.core.inbound_webhooks.providers.{p} import "
        + _verifier_class.get(p, p.capitalize() + "Verifier")
        for p in enabled_providers
    )
    registry_entries = "\n".join(
        f'    "{p}": {_verifier_class.get(p, p.capitalize() + "Verifier")}(),'
        for p in enabled_providers
    )

    content = textwrap.dedent("""\
        \"\"\"Verifier registry and handler registry for inbound webhooks.

        The verifier registry maps provider names to ``InboundVerifier`` instances.
        The handler registry maps ``(provider, event_type)`` pairs to lists of
        async handler functions registered via the ``@webhook_handler`` decorator.
        \"\"\"
        from __future__ import annotations

        {imports}
        from app.core.inbound_webhooks.base import InboundVerifier

        _VERIFIERS: dict[str, InboundVerifier] = {
        {entries}
        }

        # Handler registry: (provider, event_type) -> list[async callable]
        _HANDLERS: dict[tuple[str, str], list] = {}


        def get_verifier(provider: str) -> InboundVerifier:
            \"\"\"Return the ``InboundVerifier`` for *provider*.

            Args:
                provider: Provider name string.

            Returns:
                The matching ``InboundVerifier`` instance.

            Raises:
                HTTPException(404): If *provider* is not registered.
            \"\"\"
            if provider not in _VERIFIERS:
                from fastapi import HTTPException
                raise HTTPException(404, f"Unknown webhook provider: {provider!r}")
            return _VERIFIERS[provider]


        def register_verifier(verifier: InboundVerifier) -> None:
            \"\"\"Register a custom ``InboundVerifier`` at runtime.

            Args:
                verifier: An ``InboundVerifier`` instance with a non-empty ``name``.
            \"\"\"
            _VERIFIERS[verifier.name] = verifier


        def webhook_handler(provider: str, event_type: str):
            \"\"\"Decorator that registers an async function as a webhook handler.

            Args:
                provider: Provider name the handler listens for.
                event_type: Event type string the handler processes.

            Returns:
                A decorator that registers and returns the wrapped function unchanged.

            Example::

                @webhook_handler("stripe", "payment_intent.succeeded")
                async def on_payment(event: VerifiedEvent) -> None:
                    ...
            \"\"\"
            def deco(fn):
                _HANDLERS.setdefault((provider, event_type), []).append(fn)
                return fn

            return deco


        def get_handlers(provider: str, event_type: str) -> list:
            \"\"\"Return all handlers registered for *(provider, event_type)*.

            Args:
                provider: Provider name.
                event_type: Event type string.

            Returns:
                List of async callable handlers (may be empty).
            \"\"\"
            return _HANDLERS.get((provider, event_type), [])
        """).replace("{imports}", import_lines).replace("{entries}", registry_entries)
    dest.write_text(content)


def _write_idempotency(dest: Path, ttl: int) -> None:
    """Write ``app/core/inbound_webhooks/idempotency.py`` with Redis SET NX dedup.

    Args:
        dest: Absolute path for the new file.
        ttl: Redis key TTL in seconds.
    """
    content = textwrap.dedent("""\
        \"\"\"Redis-backed idempotency cache for inbound webhook events.

        ``claim_event`` uses ``SET NX EX`` to atomically claim an event id.
        If the key already exists the delivery is a duplicate and the caller
        should skip handler dispatch.
        \"\"\"
        from __future__ import annotations

        from app.core.redis import get_redis

        _TTL = {ttl}


        async def claim_event(provider: str, event_id: str) -> bool:
            \"\"\"Attempt to claim an inbound event id.

            Uses Redis ``SET NX EX`` for atomic first-write-wins semantics.
            The key expires after ``_TTL`` seconds so long-lived processes do
            not accumulate unbounded Redis memory.

            Args:
                provider: Provider name (used as part of the Redis key).
                event_id: Provider-assigned event identifier.

            Returns:
                ``True`` if this is the first time the event id has been seen
                (the claim was granted).  ``False`` if it is a duplicate.
            \"\"\"
            redis = await get_redis()
            key = f"inbound:webhook:{provider}:{event_id}"
            return bool(await redis.set(key, "1", nx=True, ex=_TTL))
        """).replace("{ttl}", str(ttl))
    dest.write_text(content)


def _write_inbound_crud(dest: Path) -> None:
    """Write ``app/crud/inbound_webhook.py`` with persistence helpers.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"CRUD helpers for InboundWebhook model.\"\"\"
        from __future__ import annotations

        import uuid
        from typing import Any

        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from app.models.webhook_inbound import InboundWebhook


        async def create_received(
            session: AsyncSession,
            *,
            provider: str,
            provider_event_id: str,
            event_type: str,
            payload: dict[str, Any],
            raw_headers: dict[str, str],
        ) -> InboundWebhook:
            \"\"\"Persist a newly received inbound webhook event.

            Args:
                session: Async database session.
                provider: Provider name string.
                provider_event_id: Provider-assigned event identifier.
                event_type: Provider event type string.
                payload: Parsed event payload.
                raw_headers: Lowercased request headers.

            Returns:
                The persisted ``InboundWebhook`` instance.
            \"\"\"
            row = InboundWebhook(
                provider=provider,
                provider_event_id=provider_event_id,
                event_type=event_type,
                payload=payload,
                raw_headers=raw_headers,
            )
            session.add(row)
            await session.flush()
            return row


        async def upsert_duplicate(
            session: AsyncSession,
            *,
            provider: str,
            provider_event_id: str,
            event_type: str,
        ) -> InboundWebhook:
            \"\"\"Persist a duplicate event record for audit visibility.

            Args:
                session: Async database session.
                provider: Provider name string.
                provider_event_id: Provider-assigned event id.
                event_type: Provider event type string.

            Returns:
                The persisted duplicate ``InboundWebhook`` row.
            \"\"\"
            row = InboundWebhook(
                id=uuid.uuid4(),
                provider=provider,
                provider_event_id=f"dup:{provider_event_id}:{uuid.uuid4().hex[:8]}",
                event_type=event_type,
                payload={},
                raw_headers={},
                status="duplicate",
            )
            session.add(row)
            await session.flush()
            return row


        async def get(
            session: AsyncSession, *, id: uuid.UUID | str
        ) -> InboundWebhook | None:
            \"\"\"Fetch a single inbound webhook record by id.

            Args:
                session: Async database session.
                id: UUID of the record.

            Returns:
                The ``InboundWebhook`` or ``None`` if not found.
            \"\"\"
            stmt = select(InboundWebhook).where(InboundWebhook.id == id)
            return (await session.execute(stmt)).scalar_one_or_none()


        async def list_recent(
            session: AsyncSession,
            *,
            provider: str | None = None,
            limit: int = 50,
        ) -> list[InboundWebhook]:
            \"\"\"Return recent inbound webhook records, newest first.

            Args:
                session: Async database session.
                provider: Optional provider filter.
                limit: Maximum records to return (default 50).

            Returns:
                List of ``InboundWebhook`` instances.
            \"\"\"
            stmt = select(InboundWebhook).order_by(InboundWebhook.received_at.desc()).limit(limit)
            if provider is not None:
                stmt = stmt.where(InboundWebhook.provider == provider)
            return list((await session.execute(stmt)).scalars().all())
        """)
    dest.write_text(content)


def _write_inbound_schemas(dest: Path) -> None:
    """Write ``app/schemas/inbound_webhook.py`` with Pydantic schemas.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"Pydantic schemas for inbound webhook event records.\"\"\"
        from __future__ import annotations

        import uuid
        from datetime import datetime

        from pydantic import BaseModel, ConfigDict


        class InboundWebhookPublic(BaseModel):
            \"\"\"Public representation of an inbound webhook event record.

            Attributes:
                id: UUID primary key.
                provider: Provider name (stripe / github / internal).
                provider_event_id: Provider-assigned event id.
                event_type: Provider event type string.
                status: Processing status.
                received_at: UTC timestamp of receipt.
                processed_at: UTC timestamp of handler completion.
                error: Error message if processing failed.
            \"\"\"

            model_config = ConfigDict(from_attributes=True)

            id: uuid.UUID
            provider: str
            provider_event_id: str
            event_type: str
            status: str
            received_at: datetime
            processed_at: datetime | None
            error: str | None


        class InboundWebhookAccepted(BaseModel):
            \"\"\"Response schema returned immediately when a webhook is accepted.

            Attributes:
                status: Always ``"accepted"`` for new events.
            \"\"\"

            status: str


        class InboundWebhookDuplicate(BaseModel):
            \"\"\"Response schema returned when a duplicate event is detected.

            Attributes:
                status: Always ``"duplicate"``.
            \"\"\"

            status: str
        """)
    dest.write_text(content)


def _write_inbound_worker(dest: Path) -> None:
    """Write ``app/workers/inbound_webhook_worker.py`` with the ARQ dispatcher.

    Args:
        dest: Absolute path for the new file.
    """
    content = textwrap.dedent("""\
        \"\"\"ARQ worker for processing inbound webhook events.

        ``process_inbound_webhook`` loads the persisted event, invokes registered
        handlers, and marks the record as succeeded or failed.  On exception it
        re-raises so ARQ retries the job with its own backoff schedule.

        A dead-letter pattern emerges naturally: ARQ marks a job as failed after
        ``max_retries`` attempts, leaving the ``InboundWebhook`` row in ``failed``
        status for operator inspection and manual replay.
        \"\"\"
        from __future__ import annotations

        import logging
        from datetime import datetime, timezone

        from arq.connections import RedisSettings

        from app.core.db import async_session_maker
        from app.core.inbound_webhooks.base import VerifiedEvent
        from app.core.inbound_webhooks.registry import get_handlers
        from app.crud import inbound_webhook as crud_iwh

        logger = logging.getLogger(__name__)


        async def process_inbound_webhook(ctx: dict, inbound_id: str) -> None:
            \"\"\"ARQ task: invoke handlers for an inbound webhook event.

            Args:
                ctx: ARQ context dict.
                inbound_id: UUID string of the ``InboundWebhook`` row to process.
            \"\"\"
            async with async_session_maker() as session:
                inbound = await crud_iwh.get(session, id=inbound_id)
                if not inbound or inbound.status not in ("received",):
                    return

                inbound.status = "processing"
                await session.commit()

                event = VerifiedEvent(
                    provider=inbound.provider,
                    event_id=inbound.provider_event_id,
                    event_type=inbound.event_type,
                    payload=inbound.payload,
                )

                handlers = get_handlers(inbound.provider, inbound.event_type)
                try:
                    for handler in handlers:
                        await handler(event)
                    inbound.status = "succeeded"
                    inbound.processed_at = datetime.now(timezone.utc)
                    logger.info(
                        "Processed inbound webhook provider=%s type=%s id=%s",
                        inbound.provider,
                        inbound.event_type,
                        inbound_id,
                    )
                except Exception as exc:
                    inbound.status = "failed"
                    inbound.error = repr(exc)[:500]
                    inbound.processed_at = datetime.now(timezone.utc)
                    logger.error(
                        "Handler failed for inbound webhook id=%s: %s", inbound_id, exc
                    )
                    raise  # ARQ will retry the job
                finally:
                    await session.commit()


        class WorkerSettings:
            \"\"\"ARQ worker configuration for the inbound webhook processor.

            Register this class when starting the worker::

                arq app.workers.inbound_webhook_worker.WorkerSettings
            \"\"\"

            functions = [process_inbound_webhook]
            max_jobs = 50
            max_retries = 5

            @staticmethod
            def redis_settings() -> RedisSettings:
                \"\"\"Build Redis settings from the application config.

                Returns:
                    ARQ ``RedisSettings`` for the configured ``REDIS_URL``.
                \"\"\"
                from app.core.config import settings as _settings
                return RedisSettings.from_dsn(getattr(_settings, "REDIS_URL", "redis://localhost"))
        """)
    dest.write_text(content)


def _write_inbound_routes(dest: Path, max_payload_bytes: int) -> None:
    """Write ``app/api/routes/inbound_webhooks.py`` with the receive endpoint.

    Args:
        dest: Absolute path for the new file.
        max_payload_bytes: Hard cap on body size (checked before verification).
    """
    content = textwrap.dedent("""\
        \"\"\"Inbound webhook receive endpoint.

        ``POST /webhooks/incoming/{provider}`` validates the signature, deduplicates
        via Redis, persists the event, and enqueues the ARQ handler — all in under
        50 ms.  Handlers NEVER run in the request path.
        \"\"\"
        from __future__ import annotations

        import uuid as _uuid

        from fastapi import APIRouter, Request, status
        from fastapi.responses import JSONResponse

        from app.api.deps import SessionDep
        from app.core.inbound_webhooks.idempotency import claim_event
        from app.core.inbound_webhooks.registry import get_verifier
        from app.core.queue import get_arq_pool
        from app.crud import inbound_webhook as crud_iwh

        try:
            from app.core.tenant_context import set_current_tenant
        except ImportError:  # tenant context not installed — no-op
            def set_current_tenant(tenant_id):  # type: ignore[misc]
                \"\"\"No-op fallback when multi-tenancy is not installed.\"\"\"

        router = APIRouter(prefix="/webhooks", tags=["webhooks"])

        _MAX_PAYLOAD_BYTES = {max_bytes}


        async def _persist_new_webhook(session, event, headers: dict) -> str:
            \"\"\"Create an InboundWebhook row, commit, and enqueue the ARQ job.

            Args:
                session: Async SQLAlchemy session.
                event: Verified WebhookEvent with provider, event_id, event_type, payload.
                headers: Lowercased request headers dict (stored for debugging).

            Returns:
                Always ``"accepted"``.
            \"\"\"
            inbound = await crud_iwh.create_received(
                session,
                provider=event.provider,
                provider_event_id=event.event_id,
                event_type=event.event_type,
                payload=event.payload,
                raw_headers=headers,
            )
            await session.commit()
            pool = await get_arq_pool()
            await pool.enqueue_job("process_inbound_webhook", str(inbound.id))
            return "accepted"


        @router.post("/incoming/{provider}", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
        async def receive_webhook(
            provider: str,
            request: Request,
            session: SessionDep,
        ) -> dict:
            \"\"\"Receive, verify, deduplicate, persist, and dispatch a webhook event.

            Sets tenant context from the event payload before any processing
            so background handlers execute within the correct tenant scope.

            Args:
                provider: Provider name from the path (e.g. ``stripe``).
                request: The raw FastAPI request.
                session: Injected async DB session.

            Returns:
                ``{"status": "accepted"}`` or ``{"status": "duplicate"}``.

            Raises:
                JSONResponse(413): If the body exceeds the size limit.
                HTTPException(404): If the provider is not registered.
                HTTPException(400/401): If signature verification fails.
            \"\"\"
            body = await request.body()
            if len(body) > _MAX_PAYLOAD_BYTES:
                return JSONResponse({"detail": "Payload too large"},
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
            headers = {k.lower(): v for k, v in request.headers.items()}
            event = get_verifier(provider).verify(body, headers)
            tenant_id = event.payload.get("tenant_id")
            if tenant_id:
                set_current_tenant(tenant_id)
            is_first = await claim_event(event.provider, event.event_id)
            if not is_first:
                await crud_iwh.upsert_duplicate(session, provider=event.provider,
                    provider_event_id=event.event_id, event_type=event.event_type)
                await session.commit()
                return {"status": "duplicate"}
            status_str = await _persist_new_webhook(session, event, headers)
            return {"status": status_str}


        @router.post("/replay/{event_id}", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
        async def replay_webhook(event_id: str, session: SessionDep) -> dict:
            \"\"\"Re-enqueue a previously received webhook event for reprocessing.

            Fetches the InboundWebhook record by ``event_id``, resets its status
            to ``received``, and enqueues it for the ARQ worker again.  Useful
            for ops teams recovering from handler failures.

            Args:
                event_id: UUID string of the InboundWebhook row to replay.
                session: Injected async DB session.

            Returns:
                ``{"status": "queued", "event_id": "..."}``.

            Raises:
                HTTPException(404): If no record with the given UUID exists.
            \"\"\"
            from fastapi import HTTPException  # noqa: PLC0415

            record = await crud_iwh.get(session, id=_uuid.UUID(event_id))
            if record is None:
                raise HTTPException(status_code=404, detail="Webhook event not found")

            record.status = "received"
            await session.flush()
            await session.commit()

            pool = await get_arq_pool()
            await pool.enqueue_job("process_inbound_webhook", str(record.id))

            return {"status": "queued", "event_id": event_id}
        """).replace("{max_bytes}", str(max_payload_bytes))
    dest.write_text(content)


def _write_inbound_migration(versions_dir: Path, *, has_tenants: bool = False) -> Path:
    """Generate ``alembic/versions/0016_add_webhook_receiver.py``.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.
        has_tenants: Whether multi-tenancy is installed.  When *True* the
            ``tenant_id`` column references ``tenants.id`` via FK; otherwise
            it is a plain nullable UUID column.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"

    if has_tenants:
        tenant_col = (
            '        sa.Column(\n'
            '            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id", ondelete="SET NULL"),\n'
            '            nullable=True, index=True,\n'
            '        ),'
        )
    else:
        tenant_col = (
            '        sa.Column("tenant_id", sa.Uuid(), nullable=True, index=True),'
        )

    content = textwrap.dedent("""\
        \"\"\"Add inbound_webhooks table.

        Revision ID: 0016_add_webhook_receiver
        Revises: {down_rev}
        Create Date: auto-generated by add_webhook_receiver tool
        \"\"\"
        from __future__ import annotations

        import sqlalchemy as sa
        from alembic import op

        revision = "0016_add_webhook_receiver"
        down_revision = "{down_rev}"
        branch_labels = None
        depends_on = None


        def upgrade() -> None:
            \"\"\"Create the inbound_webhooks audit table.\"\"\"
            op.create_table(
                "inbound_webhooks",
                sa.Column("id", sa.Uuid(), primary_key=True),
                TENANT_COL_PLACEHOLDER
                sa.Column("provider", sa.String(32), nullable=False),
                sa.Column("provider_event_id", sa.String(255), nullable=False),
                sa.Column("event_type", sa.String(127), nullable=False),
                sa.Column("payload", sa.JSON(), nullable=False),
                sa.Column("raw_headers", sa.JSON(), nullable=False),
                sa.Column(
                    "status",
                    sa.String(16),
                    server_default="received",
                    nullable=False,
                ),
                sa.Column("error", sa.String(500), nullable=True),
                sa.Column(
                    "received_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.func.now(),
                    nullable=False,
                ),
                sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
                sa.UniqueConstraint(
                    "provider",
                    "provider_event_id",
                    name="uq_inbound_webhook_event",
                ),
                sa.CheckConstraint(
                    "status IN ('received','processing','succeeded','failed','duplicate')",
                    name="ck_inbound_webhooks_status",
                ),
            )
            op.create_index("ix_inbound_webhooks_provider", "inbound_webhooks", ["provider"])
            op.create_index(
                "ix_inbound_webhooks_received_at", "inbound_webhooks", ["received_at"]
            )


        def downgrade() -> None:
            \"\"\"Drop the inbound_webhooks table and indexes.\"\"\"
            op.drop_index("ix_inbound_webhooks_received_at", "inbound_webhooks")
            op.drop_index("ix_inbound_webhooks_provider", "inbound_webhooks")
            op.drop_table("inbound_webhooks")
        """).replace("{down_rev}", down_rev).replace(
        "        TENANT_COL_PLACEHOLDER", tenant_col,
    )
    migration_file = versions_dir / "0016_add_webhook_receiver.py"
    migration_file.write_text(content)
    return migration_file


def _patch_config(
    config_file: Path,
    idempotency_ttl_seconds: int,
    signature_tolerance_seconds: int,
    max_payload_bytes: int,
    providers: list[str],
) -> None:
    """Inject inbound webhook settings into ``app/core/config.py``.

    Args:
        config_file: Path to the existing config module.
        idempotency_ttl_seconds: Redis key TTL.
        signature_tolerance_seconds: Clock-skew tolerance.
        max_payload_bytes: Body size cap.
        providers: List of enabled provider names.
    """
    src = config_file.read_text()
    if "INBOUND_WEBHOOK_IDEMPOTENCY_TTL" in src:
        return

    secret_lines = "\n".join(
        f'{p.upper()}_WEBHOOK_SECRET: str = ""' for p in providers
    )

    snippet = textwrap.dedent("""\

        # --- Inbound webhook receiver settings — added by add_webhook_receiver tool ---
        INBOUND_WEBHOOK_IDEMPOTENCY_TTL: int = {ttl}
        INBOUND_WEBHOOK_SIGNATURE_TOLERANCE: int = {tol}
        INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES: int = {max_bytes}
        # Per-provider secrets (set in .env):
        {secrets}
        """).replace("{ttl}", str(idempotency_ttl_seconds)) \
           .replace("{tol}", str(signature_tolerance_seconds)) \
           .replace("{max_bytes}", str(max_payload_bytes)) \
           .replace("{secrets}", secret_lines)

    config_file.write_text(src.rstrip("\n") + snippet + "\n")


def _patch_api_main(routes_init: Path) -> None:
    """Register the inbound_webhooks router in ``app/routes/__init__.py``.

    The real router assembly lives in ``app/routes/__init__.py`` (see
    ``generators/orchestrator.py``), NOT ``app/api/main.py`` (which does not
    exist in the generated scaffold). Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line=(
            "from app.api.routes.inbound_webhooks import router as inbound_webhooks_router"
        ),
        include_line="api_router.include_router(inbound_webhooks_router)",
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


def _write_queue_module(dest: Path) -> None:
    """Write ``app/core/queue.py`` with an ARQ connection pool factory.

    Created only when the base project does not already contain this module.
    The webhook routes import ``get_arq_pool()`` from this module to enqueue
    background jobs.

    Args:
        dest: Absolute destination path (``app/core/queue.py``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"ARQ connection pool factory for background job dispatch.\"\"\"

        from __future__ import annotations

        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            from arq.connections import ArqRedis

        from app.core.config import settings


        async def get_arq_pool() -> "ArqRedis":
            \"\"\"Return a connected ARQ Redis pool for enqueuing background jobs.

            Uses ``settings.REDIS_URL``. Imports ``arq`` lazily inside the
            function body so ``app.main`` boots cleanly even when the
            package is not installed — the import error only surfaces
            when a caller actually tries to enqueue a job.

            Returns:
                Connected ``ArqRedis`` pool.
            \"\"\"
            from arq.connections import RedisSettings, create_pool

            redis_url = getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
            return await create_pool(RedisSettings.from_dsn(redis_url))
    """))


def _write_redis_module(dest: Path) -> None:
    """Write ``app/core/redis.py`` with a simple async Redis client factory.

    Created only when the base project does not already contain this module.
    Realtime tools (SSE, webhook) depend on ``get_redis()`` from this module.

    Args:
        dest: Absolute destination path (``app/core/redis.py``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(textwrap.dedent("""\
        \"\"\"Async Redis client factory for realtime features (SSE, webhooks).\"\"\"

        from __future__ import annotations

        from app.core.config import settings


        async def get_redis():
            \"\"\"Return a connected async Redis client.

            Uses ``settings.REDIS_URL``.  Caller is responsible for closing
            the connection via ``await client.aclose()`` when done.

            Returns:
                Connected ``redis.asyncio.Redis`` instance.
            \"\"\"
            import redis.asyncio as _redis
            return _redis.from_url(
                getattr(settings, "REDIS_URL", "redis://localhost:6379/0"),
                decode_responses=True,
            )
    """))


def _patch_requirements(requirements_file: Path) -> None:
    """Add ``redis[hiredis]`` and ``arq`` to requirements.txt if not already present.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    lines_to_add = []
    if "redis" not in src:
        lines_to_add.append("redis[hiredis]>=5.0.0")
    if "arq" not in src:
        lines_to_add.append("arq>=0.25.0")
    if lines_to_add:
        requirements_file.write_text(src.rstrip("\n") + "\n" + "\n".join(lines_to_add) + "\n")


def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)
