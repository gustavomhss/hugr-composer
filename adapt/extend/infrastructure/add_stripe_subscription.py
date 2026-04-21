"""TOOL-065: add_stripe_subscription — add production-grade Stripe subscription billing to a FastAPI project.

Writes a ``app/core/stripe_billing.py`` lazy-import billing helper, a ``Subscription``
SQLAlchemy model (with plan_id, status, period tracking, and cancel semantics),
Pydantic request/response schemas that never leak PII (``SubscriptionPublic`` omits
``stripe_customer_id``), async CRUD helpers, REST endpoints for creating / reading /
cancelling / plan-changing subscriptions, a Stripe webhook receiver with signature
verification, an Alembic migration, and all required ``settings`` fields.

Design decisions:
* **Webhook-first state machine** — status transitions (``active``, ``past_due``,
  ``canceled``, ``trialing``) happen only via signed Stripe webhooks, never via
  client-side redirects.
* **Lazy stripe import** — ``stripe`` is imported inside every function that needs it
  so ``app.main`` boots cleanly on machines without the SDK installed.
* **Signature verification BEFORE DB work** — ``stripe.Webhook.construct_event``
  (HMAC-SHA256, 5-minute replay window) is called before any DB write.
* **Proration on plan change** — ``subscription_proration_behavior='create_prorations'``
  is passed to Stripe so mid-cycle upgrades / downgrades are automatically billed.
* **PII safety** — ``SubscriptionPublic`` omits ``stripe_customer_id``.
* **Idempotency** — a second run detects the ``StripeBilling`` fingerprint in
  ``app/core/stripe_billing.py`` and returns ``status="no_op"``.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_stripe_subscription import add_stripe_subscription

    result = add_stripe_subscription(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/stripe_billing.py", …]
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
    "name": "fastapi_resiliency_add_stripe_subscription",
    "description": (
        "Add production-grade Stripe subscription billing with Subscription model, "
        "webhook receiver, proration on plan change, and idempotent event processing."
    ),
    "tags": ["extend", "infrastructure"],
    "entry": "add_stripe_subscription",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_stripe_subscription(inp: ToolInput) -> ToolResult:
    """Add production-grade Stripe subscription billing to a FastAPI project.

    Creates the Stripe billing helper, ``Subscription`` model/schema/CRUD,
    REST routes (create, read-mine, cancel, change-plan, webhook), an Alembic
    migration, and all required settings fields.

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

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? --------------------------------------
    billing_file = app_dir / "core" / "stripe_billing.py"
    if billing_file.exists() and "StripeBilling" in billing_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "StripeBilling already present in app/core/stripe_billing.py — "
                "Stripe subscriptions already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/stripe_billing.py, app/models/subscription.py,",
                "         app/schemas/subscription.py, app/crud/subscription.py,",
                "         app/api/routes/subscriptions.py, and an Alembic migration.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_modified: list[str] = []

    # Step 1 — Stripe billing helper (lazy import so app boots without stripe)
    _write_stripe_billing(billing_file)
    files_created.append(str(billing_file))

    # Step 2 — Subscription model
    subscription_model_file = app_dir / "models" / "subscription.py"
    _write_subscription_model(subscription_model_file)
    files_created.append(str(subscription_model_file))

    # Register Subscription in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("subscription", "Subscription")])
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    subscription_schema_file = schemas_dir / "subscription.py"
    _write_subscription_schemas(subscription_schema_file)
    files_created.append(str(subscription_schema_file))

    # Step 4 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    subscription_crud_file = crud_dir / "subscription.py"
    _write_subscription_crud(subscription_crud_file)
    files_created.append(str(subscription_crud_file))

    # Step 5 — HTTP routes
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    subscriptions_route_file = routes_dir / "subscriptions.py"
    _write_subscriptions_routes(subscriptions_route_file)
    files_created.append(str(subscriptions_route_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_subscription_migration(versions_dir)
        files_created.append(str(migration_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file)
        files_modified.append(str(config_file))

    # Step 8 — register subscriptions router in app/routes/__init__.py
    routes_init_file = app_dir / "routes" / "__init__.py"
    if routes_init_file.exists():
        _patch_routes_init(routes_init_file)
        files_modified.append(str(routes_init_file))

    # Step 9 — ensure stripe in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Validate every generated Python file parses cleanly
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
            "Stripe Subscriptions added: lazy billing helper, Subscription model + schemas + CRUD,",
            "POST /subscriptions, GET /subscriptions/me, POST /subscriptions/{id}/cancel,",
            "POST /subscriptions/{id}/change-plan, and",
            "POST /subscriptions/webhook/stripe (signature-verified via "
            "stripe.Webhook.construct_event).",
            "Alembic migration for `subscriptions` table.",
            "Stripe SDK imported lazily inside StripeBilling methods — app boots "
            "cleanly without `stripe` installed (tool still adds it to requirements.txt).",
            "Proration enabled on plan change (create_prorations).",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs `stripe`",
            "alembic upgrade head",
            "Set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_BILLING_PORTAL_RETURN_URL in .env.",
            "Expose the webhook: `stripe listen --forward-to "
            "http://localhost:8000/api/v1/subscriptions/webhook/stripe` (dev) or "
            "configure an endpoint in the Stripe dashboard (prod).",
            "Restart the FastAPI app so the /subscriptions/* routes are loaded.",
            "Test: POST /subscriptions with a valid Stripe price_id and test card "
            "(4242 4242 4242 4242).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body
# ---------------------------------------------------------------------------

def _write_stripe_billing(dest: Path) -> None:
    """Write ``app/core/stripe_billing.py`` with a lazy SDK billing helper.

    All Stripe SDK calls are performed inside method bodies where the
    ``stripe`` module is imported lazily, so ``app.main`` can import
    cleanly on machines without the SDK installed.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STRIPE_BILLING_TEMPLATE)


def _write_subscription_model(dest: Path) -> None:
    """Write ``app/models/subscription.py`` with the ``Subscription`` model.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_SUBSCRIPTION_MODEL_TEMPLATE)


def _write_subscription_schemas(dest: Path) -> None:
    """Write ``app/schemas/subscription.py`` with Pydantic request/response schemas.

    ``SubscriptionPublic`` deliberately omits ``stripe_customer_id`` to
    avoid leaking PII via list endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_SUBSCRIPTION_SCHEMAS_TEMPLATE)


def _write_subscription_crud(dest: Path) -> None:
    """Write ``app/crud/subscription.py`` with async CRUD helpers.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_SUBSCRIPTION_CRUD_TEMPLATE)


def _write_subscriptions_routes(dest: Path) -> None:
    """Write ``app/api/routes/subscriptions.py`` with HTTP endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_SUBSCRIPTIONS_ROUTES_TEMPLATE)


def _write_subscription_migration(versions_dir: Path) -> Path:
    """Generate ``alembic/versions/add_stripe_subscription.py``.

    Uses ``find_migration_head`` to chain cleanly onto the existing
    Alembic head, avoiding multi-root forks.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    content = _SUBSCRIPTION_MIGRATION_TEMPLATE.replace("DOWN_REV", down_rev)
    migration_file = versions_dir / "add_stripe_subscription.py"
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
    """Inject Stripe subscription settings into the ``Settings`` class body.

    Fields are inserted INSIDE ``class Settings`` so pydantic-settings
    picks them up from environment variables.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
    """
    src = config_file.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return

    block = (
        "\n"
        "    # --- Stripe subscriptions — added by add_stripe_subscription tool ---\n"
        '    STRIPE_SECRET_KEY: str = ""\n'
        '    STRIPE_WEBHOOK_SECRET: str = ""\n'
        '    STRIPE_BILLING_PORTAL_RETURN_URL: str = "http://localhost:8000/billing"\n'
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
    """Register the subscriptions HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.subscriptions import router as subscriptions_router",
        include_line="api_router.include_router(subscriptions_router)",
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
# Templates (module-level constants — kept out of helper bodies so every
# helper function stays well under the 50-LOC budget).
# ---------------------------------------------------------------------------

_STRIPE_BILLING_TEMPLATE = textwrap.dedent("""\
    \"\"\"Stripe billing helper — lazy SDK import so the app boots without `stripe` installed.

    The Stripe Python library is imported lazily INSIDE every method that
    needs it.  This lets ``app.main`` be imported (and health-checked) on
    machines where the ``stripe`` package has not yet been pip-installed.
    \"\"\"
    from __future__ import annotations

    import logging
    from typing import Any

    from app.core.config import settings

    logger = logging.getLogger(__name__)


    class StripeBilling:
        \"\"\"Thin wrapper around the Stripe SDK for subscription operations.

        All methods import the ``stripe`` module lazily inside their bodies
        so ``app.main`` can boot without the SDK installed.

        Attributes:
            None — stateless; API key is set on each SDK call.
        \"\"\"

        def _get_stripe(self) -> Any:
            \"\"\"Return the configured ``stripe`` module (lazy import).

            Returns:
                The ``stripe`` module with ``api_key`` set from settings.
            \"\"\"
            import stripe  # local import — keeps app.main importable without stripe

            stripe.api_key = settings.STRIPE_SECRET_KEY
            return stripe

        def create_customer(self, email: str, metadata: dict[str, str] | None = None) -> Any:
            \"\"\"Create a Stripe Customer object.

            Args:
                email: Customer email address.
                metadata: Optional metadata dict to attach.

            Returns:
                Stripe Customer object.
            \"\"\"
            stripe = self._get_stripe()
            return stripe.Customer.create(email=email, metadata=metadata or {})

        def create_subscription(
            self,
            customer_id: str,
            price_id: str,
            trial_period_days: int | None = None,
        ) -> Any:
            \"\"\"Create a Stripe Subscription for the given customer and price.

            Args:
                customer_id: Stripe Customer id.
                price_id: Stripe Price id.
                trial_period_days: Optional trial period in days.

            Returns:
                Stripe Subscription object.
            \"\"\"
            stripe = self._get_stripe()
            params: dict[str, Any] = {
                "customer": customer_id,
                "items": [{"price": price_id}],
            }
            if trial_period_days:
                params["trial_period_days"] = trial_period_days
            return stripe.Subscription.create(**params)

        def cancel_subscription(self, stripe_subscription_id: str) -> Any:
            \"\"\"Cancel a Stripe Subscription at period end.

            Args:
                stripe_subscription_id: Stripe Subscription id.

            Returns:
                Updated Stripe Subscription object.
            \"\"\"
            stripe = self._get_stripe()
            return stripe.Subscription.modify(
                stripe_subscription_id,
                cancel_at_period_end=True,
            )

        def change_plan(self, stripe_subscription_id: str, new_price_id: str) -> Any:
            \"\"\"Change the plan for an existing subscription with proration.

            Args:
                stripe_subscription_id: Stripe Subscription id.
                new_price_id: New Stripe Price id.

            Returns:
                Updated Stripe Subscription object.
            \"\"\"
            stripe = self._get_stripe()
            sub = stripe.Subscription.retrieve(stripe_subscription_id)
            item_id = sub["items"]["data"][0]["id"]
            return stripe.Subscription.modify(
                stripe_subscription_id,
                items=[{"id": item_id, "price": new_price_id}],
                proration_behavior="create_prorations",
            )

        def construct_webhook_event(self, payload: bytes, sig_header: str) -> Any:
            \"\"\"Verify and construct a Stripe webhook event.

            Args:
                payload: Raw request body bytes.
                sig_header: Value of the ``Stripe-Signature`` header.

            Returns:
                Verified Stripe Event object.

            Raises:
                Exception: If signature verification fails.
            \"\"\"
            stripe = self._get_stripe()
            return stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )


    def get_stripe_billing() -> StripeBilling:
        \"\"\"Return a shared ``StripeBilling`` instance.

        Returns:
            A ``StripeBilling`` instance ready for use.
        \"\"\"
        return StripeBilling()
""")


_SUBSCRIPTION_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"SQLAlchemy model for Stripe subscription records.

    The ``subscriptions`` table tracks every Stripe Subscription attached to
    a user.  Status transitions happen only via signed webhook events — the
    application never trusts the client-side redirect as a source of truth.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import (
        Boolean,
        CheckConstraint,
        DateTime,
        ForeignKey,
        Index,
        String,
        Uuid,
        func,
    )
    from sqlalchemy.orm import Mapped, mapped_column

    from app.models.base import Base


    class Subscription(Base):
        \"\"\"A Stripe Subscription record.

        Attributes:
            id: Internal UUID primary key.
            user_id: FK to ``users.id`` — the subscriber.
            stripe_subscription_id: Stripe Subscription id (unique, indexed).
            stripe_customer_id: Stripe Customer id (PII — never exposed
                via ``SubscriptionPublic``).
            plan_id: Stripe Price id of the subscribed plan.
            status: Lifecycle status — one of ``active``, ``trialing``,
                ``past_due``, ``canceled``, ``incomplete``, ``unpaid``.
            current_period_start: UTC start of the current billing period.
            current_period_end: UTC end of the current billing period.
            cancel_at_period_end: Whether the subscription cancels at
                ``current_period_end``.
            created_at: UTC timestamp when the row was inserted.
            updated_at: UTC timestamp of the last change.
        \"\"\"

        __tablename__ = "subscriptions"

        id: Mapped[uuid.UUID] = mapped_column(
            Uuid, primary_key=True, default=uuid.uuid4
        )
        user_id: Mapped[uuid.UUID | None] = mapped_column(
            Uuid,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
        stripe_subscription_id: Mapped[str] = mapped_column(
            String(255), unique=True, nullable=False, index=True
        )
        stripe_customer_id: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        plan_id: Mapped[str] = mapped_column(String(255), nullable=False)
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, server_default="incomplete"
        )
        current_period_start: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        current_period_end: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )
        cancel_at_period_end: Mapped[bool] = mapped_column(
            Boolean, nullable=False, server_default="false"
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

        __table_args__ = (
            CheckConstraint(
                "status IN ('active','trialing','past_due','canceled','incomplete','unpaid')",
                name="ck_subscriptions_status",
            ),
            Index(
                "ix_subscriptions_user_status",
                "user_id",
                "status",
            ),
            Index(
                "ix_subscriptions_status_period_end",
                "status",
                "current_period_end",
            ),
        )
""")


_SUBSCRIPTION_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas for the Stripe subscription billing flow.

    ``SubscriptionPublic`` deliberately omits ``stripe_customer_id`` to
    avoid leaking PII via list endpoints.  Webhook handlers read the
    underlying ORM rows directly — they never round-trip through these
    schemas.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime
    from enum import Enum

    from pydantic import BaseModel, ConfigDict, Field


    class SubscriptionStatus(str, Enum):
        \"\"\"Lifecycle status of a Stripe Subscription.

        Values:
            active: Subscription is active and billing normally.
            trialing: Subscription is in a free trial period.
            past_due: Most recent payment failed; Stripe is retrying.
            canceled: Subscription was canceled.
            incomplete: Initial payment failed; awaiting retry.
            unpaid: All retries exhausted; subscription unpaid.
        \"\"\"

        active = "active"
        trialing = "trialing"
        past_due = "past_due"
        canceled = "canceled"
        incomplete = "incomplete"
        unpaid = "unpaid"


    class SubscriptionCreate(BaseModel):
        \"\"\"Request body for POST /subscriptions.

        Attributes:
            price_id: Stripe Price id to subscribe to.
            trial_period_days: Optional trial period length in days.
        \"\"\"

        price_id: str = Field(min_length=1, max_length=255)
        trial_period_days: int | None = Field(default=None, ge=1, le=365)


    class SubscriptionRead(BaseModel):
        \"\"\"Full subscription view (internal use — includes stripe fields).

        Attributes:
            id: Internal UUID.
            user_id: Owner UUID.
            stripe_subscription_id: Stripe Subscription id.
            stripe_customer_id: Stripe Customer id (PII).
            plan_id: Stripe Price id.
            status: Current lifecycle status.
            current_period_start: Billing period start.
            current_period_end: Billing period end.
            cancel_at_period_end: Whether cancellation is scheduled.
            created_at: Row creation timestamp.
            updated_at: Last update timestamp.
        \"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        user_id: uuid.UUID | None
        stripe_subscription_id: str
        stripe_customer_id: str | None
        plan_id: str
        status: SubscriptionStatus
        current_period_start: datetime | None
        current_period_end: datetime | None
        cancel_at_period_end: bool
        created_at: datetime
        updated_at: datetime


    class SubscriptionPublic(BaseModel):
        \"\"\"PII-safe public view of a subscription record.

        ``stripe_customer_id`` is intentionally omitted.
        \"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        plan_id: str
        status: SubscriptionStatus
        current_period_start: datetime | None = None
        current_period_end: datetime | None = None
        cancel_at_period_end: bool
        created_at: datetime


    class ChangePlanRequest(BaseModel):
        \"\"\"Request body for POST /subscriptions/{id}/change-plan.

        Attributes:
            new_price_id: Stripe Price id to switch to.
        \"\"\"

        new_price_id: str = Field(min_length=1, max_length=255)


    class SubscriptionListResponse(BaseModel):
        \"\"\"Envelope for GET /subscriptions/me.

        Attributes:
            data: Page of public subscription views.
            count: Total rows for the user (NOT just the page).
        \"\"\"

        data: list[SubscriptionPublic]
        count: int
""")


_SUBSCRIPTION_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the ``subscriptions`` table.

    Status transitions (active → canceled, past_due, etc.) happen only
    via webhook handlers — never from client-facing endpoints.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.subscription import Subscription


    async def create_subscription(
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None,
        stripe_subscription_id: str,
        stripe_customer_id: str | None,
        plan_id: str,
        status: str = "incomplete",
    ) -> Subscription:
        \"\"\"Insert a new Subscription row.\"\"\"
        sub = Subscription(
            user_id=user_id,
            stripe_subscription_id=stripe_subscription_id,
            stripe_customer_id=stripe_customer_id,
            plan_id=plan_id,
            status=status,
            cancel_at_period_end=False,
        )
        session.add(sub)
        await session.flush()
        return sub


    async def get_by_user(
        session: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Subscription], int]:
        \"\"\"Return (rows, total_count) for a user's subscriptions.\"\"\"
        total_stmt = (
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.user_id == user_id)
        )
        total = int((await session.execute(total_stmt)).scalar_one() or 0)
        page_stmt = (
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, total


    async def get_by_stripe_id(
        session: AsyncSession,
        stripe_subscription_id: str,
    ) -> Subscription | None:
        \"\"\"Return the Subscription row by Stripe id or ``None``.\"\"\"
        stmt = select(Subscription).where(
            Subscription.stripe_subscription_id == stripe_subscription_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


    async def update_status(
        session: AsyncSession,
        *,
        stripe_subscription_id: str,
        status: str,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> Subscription | None:
        \"\"\"Update status and billing period fields (idempotent).\"\"\"
        sub = await get_by_stripe_id(session, stripe_subscription_id)
        if sub is None:
            return None
        sub.status = status
        if current_period_start is not None:
            sub.current_period_start = current_period_start
        if current_period_end is not None:
            sub.current_period_end = current_period_end
        if cancel_at_period_end is not None:
            sub.cancel_at_period_end = cancel_at_period_end
        await session.flush()
        return sub


    async def cancel(
        session: AsyncSession,
        *,
        stripe_subscription_id: str,
    ) -> Subscription | None:
        \"\"\"Mark a subscription as canceled (idempotent).\"\"\"
        return await update_status(
            session,
            stripe_subscription_id=stripe_subscription_id,
            status="canceled",
            cancel_at_period_end=False,
        )


    async def list_active(
        session: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[Subscription]:
        \"\"\"Return all active or trialing subscriptions for *user_id*.\"\"\"
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status.in_(["active", "trialing"]),
            )
            .order_by(Subscription.created_at.desc())
        )
        return list((await session.execute(stmt)).scalars().all())
""")


_SUBSCRIPTIONS_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"HTTP routes for the Stripe subscription billing flow.

    Endpoints:
        POST /subscriptions
            Create a Stripe Subscription + Subscription row for the
            current user.  Requires authentication.

        GET /subscriptions/me
            Paginated list of the current user's subscriptions.
            Requires authentication.

        POST /subscriptions/{subscription_id}/cancel
            Schedule a subscription for cancellation at period end.
            Requires authentication and ownership.

        POST /subscriptions/{subscription_id}/change-plan
            Change the plan on an existing subscription (with proration).
            Requires authentication and ownership.

        POST /subscriptions/webhook/stripe
            Stripe webhook receiver.  Unauthenticated at HTTP level;
            authenticated via ``Stripe-Signature`` HMAC-SHA256.
    \"\"\"
    from __future__ import annotations

    import logging
    import uuid
    from datetime import datetime, timezone
    from typing import Any

    from fastapi import APIRouter, HTTPException, Query, Request, status

    from app.api.deps import CurrentUser
    from app.core.session import SessionDep
    from app.core.stripe_billing import get_stripe_billing
    from app.crud.subscription import (
        cancel,
        create_subscription,
        get_by_stripe_id,
        get_by_user,
        list_active,
        update_status,
    )
    from app.schemas.subscription import (
        ChangePlanRequest,
        SubscriptionCreate,
        SubscriptionListResponse,
        SubscriptionPublic,
    )

    logger = logging.getLogger(__name__)

    router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


    def _owner_guard(sub: Any, current_user: Any) -> None:
        \"\"\"Raise 404 unless *current_user* owns *sub* (or is superuser).\"\"\"
        is_superuser = getattr(current_user, "is_superuser", False)
        if is_superuser:
            return
        if sub.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="subscription not found",
            )


    @router.post(
        "",
        response_model=SubscriptionPublic,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_subscription_endpoint(
        body: SubscriptionCreate,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> SubscriptionPublic:
        \"\"\"Create a Stripe Subscription + pending Subscription row.\"\"\"
        billing = get_stripe_billing()
        try:
            customer = billing.create_customer(
                email=getattr(current_user, "email", ""),
            )
            stripe_sub = billing.create_subscription(
                customer_id=customer["id"],
                price_id=body.price_id,
                trial_period_days=body.trial_period_days,
            )
        except Exception as exc:
            logger.warning("stripe subscription create failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription create failed",
            ) from exc
        sub = await create_subscription(
            session,
            user_id=current_user.id,
            stripe_subscription_id=stripe_sub["id"],
            stripe_customer_id=customer["id"],
            plan_id=body.price_id,
            status=stripe_sub.get("status", "incomplete"),
        )
        await session.commit()
        return SubscriptionPublic.model_validate(sub)


    @router.get("/me", response_model=SubscriptionListResponse)
    async def list_my_subscriptions(
        current_user: CurrentUser,
        session: SessionDep,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> SubscriptionListResponse:
        \"\"\"Return the current user's subscriptions, newest first.\"\"\"
        rows, total = await get_by_user(
            session, current_user.id, limit=limit, offset=skip
        )
        data = [SubscriptionPublic.model_validate(r) for r in rows]
        return SubscriptionListResponse(data=data, count=total)


    @router.post("/{subscription_id}/cancel", response_model=SubscriptionPublic)
    async def cancel_subscription_endpoint(
        subscription_id: uuid.UUID,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> SubscriptionPublic:
        \"\"\"Schedule a subscription for cancellation at period end.\"\"\"
        from sqlalchemy import select
        from app.models.subscription import Subscription as SubscriptionModel
        stmt = select(SubscriptionModel).where(SubscriptionModel.id == subscription_id)
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="subscription not found",
            )
        _owner_guard(sub, current_user)
        billing = get_stripe_billing()
        try:
            billing.cancel_subscription(sub.stripe_subscription_id)
        except Exception as exc:
            logger.warning("stripe subscription cancel failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription cancel failed",
            ) from exc
        updated = await update_status(
            session,
            stripe_subscription_id=sub.stripe_subscription_id,
            status=sub.status,
            cancel_at_period_end=True,
        )
        await session.commit()
        return SubscriptionPublic.model_validate(updated)


    @router.post(
        "/{subscription_id}/change-plan",
        response_model=SubscriptionPublic,
    )
    async def change_plan_endpoint(
        subscription_id: uuid.UUID,
        body: ChangePlanRequest,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> SubscriptionPublic:
        \"\"\"Change the plan for an existing subscription (with proration).\"\"\"
        from sqlalchemy import select
        from app.models.subscription import Subscription as SubscriptionModel
        stmt = select(SubscriptionModel).where(SubscriptionModel.id == subscription_id)
        result = await session.execute(stmt)
        sub = result.scalar_one_or_none()
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="subscription not found",
            )
        _owner_guard(sub, current_user)
        billing = get_stripe_billing()
        try:
            billing.change_plan(sub.stripe_subscription_id, body.new_price_id)
        except Exception as exc:
            logger.warning("stripe subscription change-plan failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe subscription change-plan failed",
            ) from exc
        updated = await update_status(
            session,
            stripe_subscription_id=sub.stripe_subscription_id,
            status=sub.status,
        )
        if updated is not None:
            updated.plan_id = body.new_price_id
        await session.commit()
        return SubscriptionPublic.model_validate(updated)


    async def _handle_subscription_event(
        session: Any,
        event: dict[str, Any],
    ) -> None:
        \"\"\"Dispatch a verified Stripe subscription event to the right CRUD call.

        Unknown event types are silently acked.  Each branch is idempotent.
        \"\"\"
        event_type = event.get("type", "")
        data_obj = event.get("data", {}).get("object", {}) or {}
        stripe_sub_id = data_obj.get("id", "")
        if not stripe_sub_id:
            return

        def _parse_ts(val: int | None) -> datetime | None:
            \"\"\"Convert a Unix timestamp to a UTC-aware datetime or None.\"\"\"
            if val is None:
                return None
            return datetime.fromtimestamp(val, tz=timezone.utc)

        if event_type in (
            "customer.subscription.created",
            "customer.subscription.updated",
        ):
            await update_status(
                session,
                stripe_subscription_id=stripe_sub_id,
                status=data_obj.get("status", "incomplete"),
                current_period_start=_parse_ts(data_obj.get("current_period_start")),
                current_period_end=_parse_ts(data_obj.get("current_period_end")),
                cancel_at_period_end=bool(data_obj.get("cancel_at_period_end", False)),
            )
        elif event_type == "customer.subscription.deleted":
            await cancel(
                session,
                stripe_subscription_id=stripe_sub_id,
            )


    @router.post("/webhook/stripe")
    async def stripe_webhook(
        request: Request,
        session: SessionDep,
    ) -> dict[str, bool]:
        \"\"\"Receive and verify a Stripe webhook, then dispatch the event.\"\"\"
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        billing = get_stripe_billing()
        try:
            event = billing.construct_webhook_event(payload, sig_header)
        except Exception as exc:
            logger.warning("stripe webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid stripe signature",
            ) from exc
        await _handle_subscription_event(session, event)
        await session.commit()
        return {"received": True}
""")


_SUBSCRIPTION_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Add subscriptions table for Stripe subscription billing.

    Revision ID: add_stripe_subscription
    Revises: DOWN_REV
    Create Date: auto-generated by add_stripe_subscription tool
    \"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision = "add_stripe_subscription"
    down_revision = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def _subscription_columns() -> list:
        \"\"\"Return the column list for the subscriptions table.

        Extracted so ``upgrade()`` stays well under the 50-LOC budget.
        \"\"\"
        return [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "user_id", sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "stripe_subscription_id", sa.String(255),
                nullable=False, unique=True,
            ),
            sa.Column("stripe_customer_id", sa.String(255), nullable=True),
            sa.Column("plan_id", sa.String(255), nullable=False),
            sa.Column(
                "status", sa.String(32),
                server_default="incomplete", nullable=False,
            ),
            sa.Column(
                "current_period_start",
                sa.DateTime(timezone=True), nullable=True,
            ),
            sa.Column(
                "current_period_end",
                sa.DateTime(timezone=True), nullable=True,
            ),
            sa.Column(
                "cancel_at_period_end",
                sa.Boolean(), server_default="false", nullable=False,
            ),
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.CheckConstraint(
                "status IN ('active','trialing','past_due','canceled','incomplete','unpaid')",
                name="ck_subscriptions_status",
            ),
        ]


    def _create_subscription_indexes() -> None:
        \"\"\"Create all indexes on the subscriptions table.\"\"\"
        op.create_index(
            "ix_subscriptions_stripe_subscription_id",
            "subscriptions", ["stripe_subscription_id"], unique=True,
        )
        op.create_index(
            "ix_subscriptions_user_id",
            "subscriptions", ["user_id"],
        )
        op.create_index(
            "ix_subscriptions_user_status",
            "subscriptions", ["user_id", "status"],
        )
        op.create_index(
            "ix_subscriptions_status_period_end",
            "subscriptions", ["status", "current_period_end"],
        )


    def upgrade() -> None:
        \"\"\"Create the subscriptions table and all indexes.\"\"\"
        op.create_table("subscriptions", *_subscription_columns())
        _create_subscription_indexes()


    def downgrade() -> None:
        \"\"\"Drop the subscriptions table and its indexes.\"\"\"
        op.drop_index("ix_subscriptions_status_period_end", table_name="subscriptions")
        op.drop_index("ix_subscriptions_user_status", table_name="subscriptions")
        op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
        op.drop_index(
            "ix_subscriptions_stripe_subscription_id",
            table_name="subscriptions",
        )
        op.drop_table("subscriptions")
""")
