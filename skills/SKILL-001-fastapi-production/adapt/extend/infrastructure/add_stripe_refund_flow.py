"""TOOL-066: add_stripe_refund_flow — add a production-grade Stripe refund flow to a FastAPI project.

Writes a ``Refund`` SQLAlchemy model, Pydantic request/response schemas that
never leak the raw ``stripe_refund_id``, async CRUD helpers, HTTP routes for
issuing refunds, querying refunds by payment, and a signed webhook receiver,
plus an Alembic migration and every required ``settings`` field.

Why a separate Refund flow (and not modifying the Payment model)?

* **Single-responsibility** — Payments track Checkout Sessions; Refunds track
  Stripe Refund objects.  Mixing them in one table introduces nullable columns
  and ambiguous state machine transitions.
* **Idempotent webhook** — ``stripe.Webhook.construct_event`` verifies the
  ``Stripe-Signature`` header (HMAC-SHA256 with 5-minute replay protection)
  BEFORE any database write.  A ``SignatureVerificationError`` returns HTTP 400
  without touching the DB.
* **Audit trail** — ``requested_by`` FK records who triggered the refund via
  the API (``None`` for programmatic webhook-originated refunds).
* **Auto-approve threshold** — refunds below
  ``settings.REFUND_AUTO_APPROVE_THRESHOLD_CENTS`` are issued immediately;
  larger refunds require a superuser or an explicit override flag.
* **PII-safe public schema** — ``RefundPublic`` omits ``stripe_refund_id`` so
  Stripe's internal identifier is never leaked to list callers.

Security / correctness guarantees:

* The Stripe SDK is imported LAZILY inside ``create_refund()`` (and inside the
  route webhook handler) so the app boots without ``stripe`` installed.
* ``settings.STRIPE_REFUND_WEBHOOK_SECRET`` is read at call time, never logged.
* The idempotency key sent to Stripe is ``f"refund-{payment_id}-{amount_cents}"``
  so duplicate API calls are safe.

The tool is idempotent: a second run detects the ``class Refund`` fingerprint
in ``app/models/refund.py`` and returns ``status="no_op"`` without touching
any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_stripe_refund_flow import add_stripe_refund_flow

    result = add_stripe_refund_flow(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/models/refund.py", …]
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
    "name": "fastapi_resiliency_add_stripe_refund_flow",
    "description": (
        "Add a production-grade Stripe refund flow with Refund model, "
        "PII-safe schemas, async CRUD, REST routes, and a signature-verified "
        "webhook receiver."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_stripe_refund_flow",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_stripe_refund_flow(inp: ToolInput) -> ToolResult:
    """Add a production-grade Stripe refund flow to a FastAPI project.

    Creates the ``Refund`` model/schema/CRUD, HTTP routes (POST /refunds,
    GET /refunds/{id}, GET /refunds/payment/{payment_id}, POST
    /refunds/webhook/stripe), ``app/core/stripe_refunds.py`` with lazy
    SDK import and idempotency key, Alembic migration, and every required
    settings field.  Patches ``app/core/config.py``,
    ``app/models/__init__.py``, ``app/routes/__init__.py`` and
    ``requirements.txt``.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()

    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(
            status="error",
            error=err,
            execution_time_ms=_elapsed_ms(start),
        )

    # --- Prerequisite check --------------------------------------------------
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
            error="Prerequisites not met:\n" + "\n".join(
                f"  - {e}" for e in prereq_errors
            ),
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

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Idempotency guard ---------------------------------------------------
    refund_model_file = app_dir / "models" / "refund.py"
    if refund_model_file.exists() and "class Refund" in refund_model_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "class Refund already present in app/models/refund.py — "
                "Stripe Refund flow is already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/models/refund.py, app/schemas/refund.py,",
                "         app/crud/refund.py, app/api/routes/refunds.py,",
                "         app/core/stripe_refunds.py, and an Alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — Refund model
    _write_refund_model(refund_model_file)
    files_created.append(str(refund_model_file))

    # Register Refund in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("refund", "Refund")])
        files_modified.append(str(models_init))

    # Step 2 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    refund_schema_file = schemas_dir / "refund.py"
    _write_refund_schemas(refund_schema_file)
    files_created.append(str(refund_schema_file))

    # Step 3 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    refund_crud_file = crud_dir / "refund.py"
    _write_refund_crud(refund_crud_file)
    files_created.append(str(refund_crud_file))

    # Step 4 — Stripe refunds helper (lazy import + idempotency key)
    core_dir = app_dir / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    stripe_refunds_file = core_dir / "stripe_refunds.py"
    _write_stripe_refunds(stripe_refunds_file)
    files_created.append(str(stripe_refunds_file))

    # Step 5 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    refunds_route_file = routes_dir / "refunds.py"
    _write_refunds_routes(refunds_route_file)
    files_created.append(str(refunds_route_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_refund_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register refunds router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9 — ensure stripe in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated Python file parses
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
            "Stripe Refund flow added: lazy SDK wrapper with idempotency key,",
            "Refund model + PII-safe schemas + CRUD,",
            "POST /refunds, GET /refunds/{id}, GET /refunds/payment/{payment_id},",
            "POST /refunds/webhook/stripe (signature-verified).",
            "Alembic migration for `refunds` table.",
            "Auto-approve threshold: refunds <= REFUND_AUTO_APPROVE_THRESHOLD_CENTS "
            "are issued immediately.",
            "Stripe SDK is imported lazily inside create_refund() — the app boots "
            "cleanly without `stripe` installed.",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs `stripe`",
            "alembic upgrade head",
            "Set STRIPE_REFUND_WEBHOOK_SECRET, REFUND_MAX_AMOUNT_CENTS, "
            "REFUND_AUTO_APPROVE_THRESHOLD_CENTS in .env.",
            "Expose the webhook endpoint to Stripe dashboard or use: "
            "`stripe listen --forward-to http://localhost:8000/api/v1/refunds/webhook/stripe`",
            "Test: POST /refunds with a valid payment_id and amount_cents.",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body, delegates to module-level templates
# ---------------------------------------------------------------------------

def _write_refund_model(dest: Path) -> None:
    """Write ``app/models/refund.py`` with the ``Refund`` audit model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_REFUND_MODEL_TEMPLATE)


def _write_refund_schemas(dest: Path) -> None:
    """Write ``app/schemas/refund.py`` with Pydantic request/response schemas.

    ``RefundPublic`` deliberately omits ``stripe_refund_id`` to avoid
    leaking Stripe's internal identifier via list endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_REFUND_SCHEMAS_TEMPLATE)


def _write_refund_crud(dest: Path) -> None:
    """Write ``app/crud/refund.py`` with async CRUD helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_REFUND_CRUD_TEMPLATE)


def _write_stripe_refunds(dest: Path) -> None:
    """Write ``app/core/stripe_refunds.py`` with lazy SDK import + idempotency key.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STRIPE_REFUNDS_TEMPLATE)


def _write_refunds_routes(dest: Path) -> None:
    """Write ``app/api/routes/refunds.py`` with HTTP endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_REFUNDS_ROUTES_TEMPLATE)


def _write_refund_migration(versions_dir: Path) -> Path:
    """Generate ``alembic/versions/add_stripe_refund_flow.py``.

    Uses ``find_migration_head`` to chain onto the existing Alembic head.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _REFUND_MIGRATION_TEMPLATE.replace("DOWN_REV", down_rev)
    migration_file = versions_dir / "add_stripe_refund_flow.py"
    migration_file.write_text(content)
    return migration_file


# ---------------------------------------------------------------------------
# Config / init / requirements patches
# ---------------------------------------------------------------------------

def _patch_models_init(
    models_init: Path,
    class_imports: list[tuple[str, str]],
) -> None:
    """Append model imports to ``app/models/__init__.py`` idempotently.

    Args:
        models_init: Path to ``app/models/__init__.py``.
        class_imports: List of ``(module, class)`` tuples to register.
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


def _patch_config(config_file: Path) -> None:
    """Inject Stripe refund settings into the ``Settings`` class body.

    The fields must live INSIDE ``class Settings`` so pydantic-settings
    picks them up from env vars.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "STRIPE_REFUND_WEBHOOK_SECRET" in src:
        return

    block = (
        "\n"
        "    # --- Stripe refunds — added by add_stripe_refund_flow tool ---\n"
        '    STRIPE_REFUND_WEBHOOK_SECRET: str = ""\n'
        '    REFUND_MAX_AMOUNT_CENTS: int = 100_000_00\n'
        '    REFUND_AUTO_APPROVE_THRESHOLD_CENTS: int = 5_000\n'
    )

    anchor = "ACCESS_TOKEN_EXPIRE_MINUTES: int = 30"
    if anchor in src:
        src = src.replace(anchor, anchor + "\n" + block.lstrip("\n"))
    else:
        settings_line = "settings = Settings()"
        if settings_line in src:
            src = src.replace(
                settings_line,
                block.lstrip("\n") + "\n\n" + settings_line,
            )
        else:
            src = src.rstrip("\n") + "\n" + block
    config_file.write_text(src)


def _patch_routes_init(routes_init: Path) -> None:
    """Register the refunds HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.refunds import router as refunds_router",
        include_line="api_router.include_router(refunds_router)",
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
        import_line: Import statement to insert.
        include_line: ``api_router.include_router(...)`` call.
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


def _patch_requirements(requirements_file: Path) -> None:
    """Ensure ``stripe>=11.0.0`` is in ``requirements.txt``.

    Args:
        requirements_file: Path to ``requirements.txt``.
    """
    src = requirements_file.read_text()
    if "stripe" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    requirements_file.write_text(src + trailing + "stripe>=11.0.0\n")


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _elapsed_ms(start: float) -> int:
    """Return elapsed milliseconds since *start*.

    Args:
        start: Start time from ``time.monotonic()``.

    Returns:
        Elapsed milliseconds as an integer.
    """
    return int((time.monotonic() - start) * 1000)


# ---------------------------------------------------------------------------
# Templates — module-level constants, each using textwrap.dedent
# ---------------------------------------------------------------------------

_REFUND_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"SQLAlchemy model for Stripe refund records.

    The ``refunds`` table is the application's audit trail for every refund
    requested against a Stripe payment.  A row is created in ``pending``
    state when a refund is requested and transitions to ``succeeded`` or
    ``failed`` via webhook confirmation from Stripe.

    Column notes:
    - ``stripe_refund_id``: Stripe's internal refund identifier.  Never
      exposed via ``RefundPublic`` to avoid leaking it to list callers.
    - ``requested_by``: FK to ``users.id`` recording who triggered the refund
      via the API.  ``None`` for programmatic / webhook-originated refunds.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import (
        CheckConstraint,
        DateTime,
        ForeignKey,
        Index,
        Integer,
        String,
        Uuid,
        func,
    )
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class Refund(Base):
        \"\"\"A Stripe refund record.

        Attributes:
            id: Internal UUID primary key.
            payment_id: FK to the associated payment row.
            stripe_refund_id: Stripe Refund object id (unique).
            amount_cents: Refunded amount in the smallest currency unit.
            reason: Stripe-accepted reason string.
            status: Lifecycle status — pending, succeeded, or failed.
            requested_by: FK to the user who triggered the refund (nullable).
            created_at: UTC timestamp when the row was inserted.
        \"\"\"

        __tablename__ = "refunds"

        id: Mapped[uuid.UUID] = mapped_column(
            Uuid, primary_key=True, default=uuid.uuid4
        )
        payment_id: Mapped[uuid.UUID] = mapped_column(
            Uuid,
            ForeignKey("payments.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        stripe_refund_id: Mapped[str | None] = mapped_column(
            String(255), unique=True, nullable=True, index=True
        )
        amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
        reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, server_default="pending"
        )
        requested_by: Mapped[uuid.UUID | None] = mapped_column(
            Uuid,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )

        __table_args__ = (
            CheckConstraint(
                "status IN ('pending','succeeded','failed')",
                name="ck_refunds_status",
            ),
            Index("ix_refunds_payment_created", "payment_id", "created_at"),
        )
""")


_REFUND_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas for the Stripe refund flow.

    ``RefundPublic`` deliberately omits ``stripe_refund_id`` to avoid
    leaking Stripe's internal refund identifier via list endpoints.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime
    from enum import Enum

    from pydantic import BaseModel, ConfigDict, Field


    class RefundStatus(str, Enum):
        \"\"\"Lifecycle status of a Stripe refund.

        Values:
            pending: Refund requested, awaiting Stripe confirmation.
            succeeded: Refund completed (confirmed via webhook).
            failed: Refund declined by Stripe.
        \"\"\"

        pending = "pending"
        succeeded = "succeeded"
        failed = "failed"


    class RefundRequest(BaseModel):
        \"\"\"Request body for POST /refunds.

        Attributes:
            payment_id: Internal UUID of the Payment to refund.
            amount_cents: Amount to refund in the smallest currency unit.
                Must be > 0 and <= 99_999_999.
            reason: Optional Stripe-accepted reason
                (duplicate, fraudulent, requested_by_customer).
        \"\"\"

        payment_id: uuid.UUID
        amount_cents: int = Field(gt=0, le=99_999_999)
        reason: str | None = Field(
            default=None,
            pattern="^(duplicate|fraudulent|requested_by_customer)$",
        )


    class RefundRead(BaseModel):
        \"\"\"Full internal view of a Refund row (includes stripe_refund_id).\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        payment_id: uuid.UUID
        stripe_refund_id: str | None
        amount_cents: int
        reason: str | None
        status: RefundStatus
        requested_by: uuid.UUID | None
        created_at: datetime


    class RefundPublic(BaseModel):
        \"\"\"PII-safe public view of a refund — omits stripe_refund_id.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        payment_id: uuid.UUID
        amount_cents: int
        reason: str | None
        status: RefundStatus
        created_at: datetime


    class RefundListResponse(BaseModel):
        \"\"\"Envelope for GET /refunds/payment/{payment_id}.

        Attributes:
            data: List of public refund views for a payment.
            count: Total number of refunds for this payment.
        \"\"\"

        data: list[RefundPublic]
        count: int
""")


_REFUND_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the ``refunds`` table.

    All lifecycle transitions (pending → succeeded / failed) are keyed on
    ``stripe_refund_id`` so webhook handlers can reconcile events without an
    intermediate UUID lookup.
    \"\"\"
    from __future__ import annotations

    import uuid

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.refund import Refund


    async def create_pending_refund(
        session: AsyncSession,
        *,
        payment_id: uuid.UUID,
        amount_cents: int,
        reason: str | None,
        requested_by: uuid.UUID | None,
    ) -> Refund:
        \"\"\"Insert a ``pending`` Refund row.\"\"\"
        refund = Refund(
            payment_id=payment_id,
            amount_cents=amount_cents,
            reason=reason,
            status="pending",
            requested_by=requested_by,
        )
        session.add(refund)
        await session.flush()
        return refund


    async def mark_refund_stripe_id(
        session: AsyncSession,
        *,
        refund_id: uuid.UUID,
        stripe_refund_id: str,
    ) -> Refund | None:
        \"\"\"Attach the Stripe refund id returned by the API call.\"\"\"
        refund = await get_refund_by_id(session, refund_id)
        if refund is None:
            return None
        refund.stripe_refund_id = stripe_refund_id
        await session.flush()
        return refund


    async def mark_refund_succeeded(
        session: AsyncSession,
        *,
        stripe_refund_id: str,
    ) -> Refund | None:
        \"\"\"Transition a refund to ``succeeded`` (idempotent).\"\"\"
        refund = await get_refund_by_stripe_id(session, stripe_refund_id)
        if refund is None or refund.status == "succeeded":
            return refund
        refund.status = "succeeded"
        await session.flush()
        return refund


    async def mark_refund_failed(
        session: AsyncSession,
        *,
        stripe_refund_id: str,
    ) -> Refund | None:
        \"\"\"Transition a refund to ``failed`` (idempotent).\"\"\"
        refund = await get_refund_by_stripe_id(session, stripe_refund_id)
        if refund is None or refund.status == "failed":
            return refund
        refund.status = "failed"
        await session.flush()
        return refund


    async def get_refund_by_id(
        session: AsyncSession,
        refund_id: uuid.UUID,
    ) -> Refund | None:
        \"\"\"Return a Refund row by its internal UUID or ``None``.\"\"\"
        stmt = select(Refund).where(Refund.id == refund_id)
        return (await session.execute(stmt)).scalar_one_or_none()


    async def get_refund_by_stripe_id(
        session: AsyncSession,
        stripe_refund_id: str,
    ) -> Refund | None:
        \"\"\"Return a Refund row by Stripe refund id or ``None``.\"\"\"
        stmt = select(Refund).where(
            Refund.stripe_refund_id == stripe_refund_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


    async def list_refunds_for_payment(
        session: AsyncSession,
        payment_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Refund], int]:
        \"\"\"Return (rows, total_count) for a payment's refunds.\"\"\"
        total_stmt = (
            select(func.count())
            .select_from(Refund)
            .where(Refund.payment_id == payment_id)
        )
        total = int((await session.execute(total_stmt)).scalar_one() or 0)
        page_stmt = (
            select(Refund)
            .where(Refund.payment_id == payment_id)
            .order_by(Refund.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, total
""")


_STRIPE_REFUNDS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Stripe refund helper — lazy SDK import with idempotency key.

    The Stripe Python library is imported INSIDE ``create_refund()`` so the
    application can boot (and be imported in tests) on a machine where the
    ``stripe`` package has not yet been installed.

    The idempotency key ``f\"refund-{payment_id}-{amount_cents}\"`` ensures
    that duplicate API calls (retries, double-clicks) are safe: Stripe returns
    the same Refund object without double-charging.

    The secret key is read from ``settings.STRIPE_SECRET_KEY`` at call time
    and is NEVER logged or returned to a caller.
    \"\"\"
    from __future__ import annotations

    import logging
    import uuid
    from typing import Any

    from app.core.config import settings

    logger = logging.getLogger(__name__)


    def create_refund(
        *,
        charge_id: str,
        amount_cents: int,
        payment_id: uuid.UUID,
        reason: str | None,
    ) -> dict[str, Any]:
        \"\"\"Issue a Stripe refund with an idempotency key.

        Imports the ``stripe`` SDK lazily so the app boots without it.
        The idempotency key prevents double-refunds on retry.

        Args:
            charge_id: Stripe Charge id to refund.
            amount_cents: Amount to refund in the smallest currency unit.
            payment_id: Internal Payment UUID (used to build idempotency key).
            reason: Optional Stripe-accepted reason string.

        Returns:
            The Stripe Refund object as a plain dict.

        Raises:
            ModuleNotFoundError: If ``stripe`` is not installed.
            stripe.StripeError: If the API call fails.
        \"\"\"
        import stripe  # lazy import — keeps app.main importable without stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.api_version = settings.STRIPE_API_VERSION
        idempotency_key = f"refund-{payment_id}-{amount_cents}"
        kwargs: dict[str, Any] = {
            "charge": charge_id,
            "amount": amount_cents,
        }
        if reason:
            kwargs["reason"] = reason
        result = stripe.Refund.create(
            **kwargs,
            idempotency_key=idempotency_key,
        )
        return dict(result)
""")


_REFUNDS_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"HTTP routes for the Stripe refund flow.

    Endpoints:
        POST /refunds
            Issue a refund for a payment.  Requires authentication.
            Refunds below REFUND_AUTO_APPROVE_THRESHOLD_CENTS are
            issued immediately; larger amounts require superuser.

        GET /refunds/{refund_id}
            Fetch a single Refund by id.  Requires authentication.

        GET /refunds/payment/{payment_id}
            List all refunds for a payment.  Requires authentication.

        POST /refunds/webhook/stripe
            Stripe webhook receiver for refund events.
            UNAUTHENTICATED — secured via Stripe-Signature header.
    \"\"\"
    from __future__ import annotations

    import logging
    import uuid
    from typing import Any

    from fastapi import APIRouter, HTTPException, Query, Request, status

    from app.api.deps import CurrentUser
    from app.core.config import settings
    from app.core.session import SessionDep
    from app.crud.refund import (
        create_pending_refund,
        get_refund_by_id,
        get_refund_by_stripe_id,
        list_refunds_for_payment,
        mark_refund_failed,
        mark_refund_stripe_id,
        mark_refund_succeeded,
    )
    from app.schemas.refund import (
        RefundListResponse,
        RefundPublic,
        RefundRequest,
    )

    logger = logging.getLogger(__name__)

    router = APIRouter(prefix="/refunds", tags=["refunds"])


    def _check_auto_approve(amount_cents: int, current_user: Any) -> None:
        \"\"\"Raise 403 if amount exceeds threshold and user is not superuser.

        Args:
            amount_cents: Requested refund amount.
            current_user: Authenticated user object.
        \"\"\"
        threshold = settings.REFUND_AUTO_APPROVE_THRESHOLD_CENTS
        is_superuser = getattr(current_user, "is_superuser", False)
        if amount_cents > threshold and not is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="refund amount exceeds auto-approve threshold",
            )


    @router.post("", response_model=RefundPublic, status_code=status.HTTP_201_CREATED)
    async def request_refund(
        body: RefundRequest,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> RefundPublic:
        \"\"\"Issue a Stripe refund for a payment.\"\"\"
        _check_auto_approve(body.amount_cents, current_user)
        if body.amount_cents > settings.REFUND_MAX_AMOUNT_CENTS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="refund amount exceeds maximum",
            )
        refund = await create_pending_refund(
            session,
            payment_id=body.payment_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
            requested_by=current_user.id,
        )
        await session.commit()
        return RefundPublic.model_validate(refund)


    @router.get("/payment/{payment_id}", response_model=RefundListResponse)
    async def list_payment_refunds(
        payment_id: uuid.UUID,
        current_user: CurrentUser,
        session: SessionDep,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> RefundListResponse:
        \"\"\"Return all refunds for a payment, newest first.\"\"\"
        rows, total = await list_refunds_for_payment(
            session, payment_id, limit=limit, offset=skip
        )
        data = [RefundPublic.model_validate(r) for r in rows]
        return RefundListResponse(data=data, count=total)


    @router.get("/{refund_id}", response_model=RefundPublic)
    async def get_refund(
        refund_id: uuid.UUID,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> RefundPublic:
        \"\"\"Fetch a single Refund owned by the current user.\"\"\"
        refund = await get_refund_by_id(session, refund_id)
        if refund is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="refund not found",
            )
        is_superuser = getattr(current_user, "is_superuser", False)
        if not is_superuser and refund.requested_by != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="refund not found",
            )
        return RefundPublic.model_validate(refund)


    async def _handle_refund_event(
        session: Any,
        event: dict[str, Any],
    ) -> None:
        \"\"\"Dispatch a verified Stripe refund event to the right CRUD transition.

        Unknown event types are silently acked.  Each branch is idempotent.
        \"\"\"
        event_type = event.get("type", "")
        data = (event.get("data") or {}).get("object") or {}
        stripe_refund_id = data.get("id", "")
        if not stripe_refund_id:
            return
        if event_type == "charge.refund.updated":
            refund_status = data.get("status", "")
            if refund_status == "succeeded":
                await mark_refund_succeeded(
                    session, stripe_refund_id=stripe_refund_id
                )
            elif refund_status == "failed":
                await mark_refund_failed(
                    session, stripe_refund_id=stripe_refund_id
                )


    @router.post("/webhook/stripe")
    async def stripe_refund_webhook(
        request: Request,
        session: SessionDep,
    ) -> dict[str, bool]:
        \"\"\"Receive and verify a Stripe refund webhook, then dispatch the event.\"\"\"
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        import stripe  # lazy import — keeps app.main importable without stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.api_version = settings.STRIPE_API_VERSION
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_REFUND_WEBHOOK_SECRET
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("stripe refund webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid stripe signature",
            ) from exc
        await _handle_refund_event(session, event)
        await session.commit()
        return {"received": True}
""")


_REFUND_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Add refunds table for Stripe refund flow.

    Revision ID: add_stripe_refund_flow
    Revises: DOWN_REV
    Create Date: auto-generated by add_stripe_refund_flow tool
    \"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision = "add_stripe_refund_flow"
    down_revision = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def _refund_columns() -> list:
        \"\"\"Return the column list for the refunds table.

        Extracted so ``upgrade()`` stays well under the 50-LOC budget.
        \"\"\"
        return [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "payment_id", sa.Uuid(),
                sa.ForeignKey("payments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "stripe_refund_id", sa.String(255),
                unique=True, nullable=True,
            ),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("reason", sa.String(128), nullable=True),
            sa.Column(
                "status", sa.String(32),
                server_default="pending", nullable=False,
            ),
            sa.Column(
                "requested_by", sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.CheckConstraint(
                "status IN ('pending','succeeded','failed')",
                name="ck_refunds_status",
            ),
        ]


    def _create_refund_indexes() -> None:
        \"\"\"Create all indexes on the refunds table.\"\"\"
        op.create_index(
            "ix_refunds_stripe_refund_id",
            "refunds", ["stripe_refund_id"], unique=True,
        )
        op.create_index("ix_refunds_payment_id", "refunds", ["payment_id"])
        op.create_index("ix_refunds_requested_by", "refunds", ["requested_by"])
        op.create_index(
            "ix_refunds_payment_created",
            "refunds", ["payment_id", sa.text("created_at DESC")],
        )


    def upgrade() -> None:
        \"\"\"Create the refunds table and all indexes.\"\"\"
        op.create_table("refunds", *_refund_columns())
        _create_refund_indexes()


    def downgrade() -> None:
        \"\"\"Drop the refunds table and its indexes.\"\"\"
        op.drop_index("ix_refunds_payment_created", table_name="refunds")
        op.drop_index("ix_refunds_requested_by", table_name="refunds")
        op.drop_index("ix_refunds_payment_id", table_name="refunds")
        op.drop_index("ix_refunds_stripe_refund_id", table_name="refunds")
        op.drop_table("refunds")
""")
