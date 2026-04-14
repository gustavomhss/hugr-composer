"""TOOL-023: add_stripe_checkout — add a production-grade Stripe Checkout flow to a FastAPI project.

Writes an ``app/core/stripe_client.py`` lazy-import wrapper around the Stripe
Python SDK, a ``Payment`` SQLAlchemy model (tenant-aware when
``app/models/tenant.py`` exists), Pydantic request/response schemas that never
leak PII, async CRUD helpers keyed on the Stripe Checkout Session id,
HTTP routes for creating a Checkout Session, fetching a single payment,
listing the current user's payments, and a signed webhook receiver that
terminates Stripe's ``checkout.session.completed`` /
``checkout.session.async_payment_succeeded`` /
``checkout.session.async_payment_failed`` / ``charge.refunded`` events
idempotently, an Alembic migration, and every required ``settings`` field.

Why Stripe Checkout (and not a custom PaymentIntent flow)?

* **Hosted UI** — Stripe owns the PCI surface; the application never
  touches a card number, so the scope of PCI DSS compliance collapses
  from ``SAQ D`` to ``SAQ A``.
* **Strong Customer Authentication** — 3DS2 / SCA flows, Apple Pay,
  Google Pay, Klarna, etc. are handled inside Checkout without any
  extra code.
* **Idempotent webhooks** — the ``stripe.Webhook.construct_event`` helper
  verifies the ``Stripe-Signature`` header (HMAC-SHA256 with replay
  protection via a 5-minute timestamp tolerance) before the handler
  touches the database.

Security / correctness guarantees:

* The Stripe SDK is imported LAZILY inside ``get_stripe()`` so the
  application can boot without ``stripe`` installed (the tool does add
  ``stripe`` to ``requirements.txt`` but test scaffolds run the boot
  check without it).
* ``settings.STRIPE_SECRET_KEY`` is read on each ``get_stripe()`` call
  but is NEVER logged or returned to a caller.  The ``Payment`` model
  explicitly omits the customer id from its public view schema.
* Every webhook event is verified with
  ``stripe.Webhook.construct_event`` (includes replay protection); a
  ``SignatureVerificationError`` returns HTTP 400 before any DB write.
* Unknown event types are acked with HTTP 200 so Stripe stops retrying;
  known events are dispatched through small handlers that each fit
  inside 50 LOC (enforced in tests via AST walking).
* The ``Payment`` row is created in ``pending`` state when the
  Checkout Session is opened, and transitions to ``succeeded``,
  ``failed``, or ``refunded`` only via webhook confirmation — the
  client-side ``success_url`` is treated as a UX hint, never as a
  source of truth.
* Tenant-aware: the ``tenant_id`` FK is only emitted when
  ``app/models/tenant.py`` exists, mirroring the
  ``add_webhook_receiver`` pattern.

The tool is idempotent: a second run detects the ``get_stripe``
fingerprint in ``app/core/stripe_client.py`` and returns
``status="no_op"`` without touching any file.

Example::

    from adapt.contracts import ToolInput
    from adapt.extend.infrastructure.add_stripe_checkout import add_stripe_checkout

    result = add_stripe_checkout(ToolInput(project_dir="/path/to/project"))
    print(result.status)        # "success"
    print(result.files_created) # ["…/app/core/stripe_client.py", …]
    print(result.next_steps)    # ["alembic upgrade head", …]
"""

from __future__ import annotations

import ast
import textwrap
import time
from pathlib import Path

from adapt.contracts import ToolInput, ToolResult, validate_project_dir
from adapt.contracts.migration_helper import find_migration_head


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def add_stripe_checkout(
    inp: ToolInput,
    *,
    api_version: str = "2024-06-20",
    success_url: str = "http://localhost:8000/success",
    cancel_url: str = "http://localhost:8000/cancel",
) -> ToolResult:
    """Add a production-grade Stripe Checkout flow to a FastAPI project.

    Creates the Stripe SDK wrapper, ``Payment`` model/schema/CRUD, HTTP
    routes (create session, get single, list mine, webhook receiver),
    Alembic migration, and every required Stripe settings field.
    Patches ``app/core/config.py``, ``app/models/__init__.py``,
    ``app/routes/__init__.py`` and ``requirements.txt``.  Does NOT patch
    ``app/main.py`` — the Stripe SDK is stateless and requires no
    lifespan hook.

    Args:
        inp: ``ToolInput`` with ``project_dir`` (absolute path) and optional
            ``dry_run`` flag.
        api_version: Stripe API version pin (default ``"2024-06-20"``).
            Maps to ``settings.STRIPE_API_VERSION``.  Pinning protects
            the integration from silent breaking changes when Stripe
            rolls forward.
        success_url: Default redirect URL Stripe sends the customer to
            after a successful payment.  Maps to
            ``settings.STRIPE_CHECKOUT_SUCCESS_URL``.  Each request may
            override this via the ``CheckoutSessionCreate.success_url``
            field.
        cancel_url: Default redirect URL Stripe sends the customer to
            after a cancelled payment.  Maps to
            ``settings.STRIPE_CHECKOUT_CANCEL_URL``.

    Returns:
        ``ToolResult`` with ``status``, ``files_created``, ``files_modified``,
        ``notes``, and ``next_steps``.
    """
    start = time.monotonic()
    err = validate_project_dir(inp.project_dir)
    if err:
        return ToolResult(status="error", error=err)

    project = Path(inp.project_dir)
    app_dir = project / "app"

    # --- Pre-flight: already installed? ------------------------------------
    client_file = app_dir / "core" / "stripe_client.py"
    if client_file.exists() and "get_stripe" in client_file.read_text():
        return ToolResult(
            status="no_op",
            notes=[
                "get_stripe already present in app/core/stripe_client.py — "
                "Stripe Checkout is already installed, skipped.",
            ],
            execution_time_ms=_elapsed_ms(start),
        )

    has_tenants = (app_dir / "models" / "tenant.py").exists()

    if inp.dry_run:
        return ToolResult(
            status="success",
            notes=[
                "[dry_run] Would create app/core/stripe_client.py, app/models/payment.py,",
                "         app/schemas/payment.py, app/crud/payment.py, app/api/routes/payments.py,",
                "         and an Alembic migration for the `payments` table"
                + (" (tenant-aware)" if has_tenants else "")
                + ".",
                f"         Stripe api_version={api_version}, success_url={success_url}, "
                f"cancel_url={cancel_url}.",
                "[dry_run] No files written.",
            ],
            next_steps=["Re-run without dry_run=True to apply changes."],
            execution_time_ms=_elapsed_ms(start),
        )

    files_created: list[str] = []
    files_modified: list[str] = []

    # Step 1 — Stripe SDK wrapper (lazy import so app boots without stripe)
    _write_stripe_client(client_file)
    files_created.append(str(client_file))

    # Step 2 — Payment model
    payment_model_file = app_dir / "models" / "payment.py"
    _write_payment_model(payment_model_file, has_tenants=has_tenants)
    files_created.append(str(payment_model_file))

    # Register Payment in app/models/__init__.py
    models_init = app_dir / "models" / "__init__.py"
    if models_init.exists():
        _patch_models_init(models_init, [("payment", "Payment")])
        files_modified.append(str(models_init))

    # Step 3 — Pydantic schemas
    schemas_dir = app_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    payment_schema_file = schemas_dir / "payment.py"
    _write_payment_schemas(payment_schema_file)
    files_created.append(str(payment_schema_file))

    # Step 4 — CRUD
    crud_dir = app_dir / "crud"
    crud_dir.mkdir(parents=True, exist_ok=True)
    payment_crud_file = crud_dir / "payment.py"
    _write_payment_crud(payment_crud_file)
    files_created.append(str(payment_crud_file))

    # Step 5 — HTTP routes (create session + get + list + webhook)
    routes_dir = app_dir / "api" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    payments_route_file = routes_dir / "payments.py"
    _write_payments_routes(payments_route_file)
    files_created.append(str(payments_route_file))

    # Step 6 — Alembic migration
    versions_dir = project / "alembic" / "versions"
    if versions_dir.exists():
        migration_file = _write_payment_migration(
            versions_dir, has_tenants=has_tenants
        )
        files_created.append(str(migration_file))

    # Step 7 — patch config
    config_file = app_dir / "core" / "config.py"
    if config_file.exists():
        _patch_config(config_file, api_version, success_url, cancel_url)
        files_modified.append(str(config_file))

    # Step 8 — register payments router in app/routes/__init__.py
    routes_init = app_dir / "routes" / "__init__.py"
    if routes_init.exists():
        _patch_routes_init(routes_init)
        files_modified.append(str(routes_init))

    # Step 9 — ensure stripe in requirements.txt
    requirements_file = project / "requirements.txt"
    if requirements_file.exists():
        _patch_requirements(requirements_file)
        files_modified.append(str(requirements_file))

    # Step 10 — patch .env.example (documentation only)
    env_example = project / ".env.example"
    if env_example.exists():
        _patch_env_example(env_example)
        files_modified.append(str(env_example))

    # Validate every generated Python file parses
    for path_str in files_created:
        p = Path(path_str)
        if p.suffix == ".py":
            _assert_parses(p)

    return ToolResult(
        status="success",
        files_created=files_created,
        files_modified=files_modified,
        notes=[
            "Stripe Checkout added: lazy SDK wrapper, Payment model + schemas + CRUD,",
            "POST /payments/checkout, GET /payments/{id}, GET /payments/me, and",
            "POST /payments/webhook/stripe (signature-verified via "
            "stripe.Webhook.construct_event).",
            "Alembic migration for `payments` table"
            + (" (tenant-aware)" if has_tenants else "")
            + ".",
            f"Stripe api_version pinned to {api_version}.",
            "Stripe SDK is imported lazily inside get_stripe() — the app boots cleanly "
            "without `stripe` installed (the tool still adds it to requirements.txt).",
        ],
        next_steps=[
            "pip install -r requirements.txt  # installs `stripe`",
            "alembic upgrade head",
            "Set STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET in .env.",
            "Expose the webhook endpoint: `stripe listen --forward-to "
            "http://localhost:8000/api/v1/payments/webhook/stripe` (dev) or configure "
            "an endpoint in the Stripe dashboard (prod).",
            "Restart the FastAPI app so the /payments/* routes are loaded.",
            "Test: POST /payments/checkout with a test amount/currency; open the "
            "returned checkout_url; complete with a Stripe test card (4242 4242 4242 4242).",
        ],
        execution_time_ms=_elapsed_ms(start),
    )


# ---------------------------------------------------------------------------
# File writers — each helper ≤50 LOC body, delegates templates to module-level
# constants / pure string replacement (never f-strings with braces).
# ---------------------------------------------------------------------------

def _write_stripe_client(dest: Path) -> None:
    """Write ``app/core/stripe_client.py`` with a lazy SDK wrapper.

    The wrapper imports the ``stripe`` module lazily inside ``get_stripe()``
    so the application can boot (and be imported in tests) on a machine
    where the Stripe SDK has not yet been installed.  The API key and
    version are assigned on every call — this is a cheap attribute set
    and keeps the singleton stateless.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_STRIPE_CLIENT_TEMPLATE)


def _write_payment_model(dest: Path, *, has_tenants: bool = False) -> None:
    """Write ``app/models/payment.py`` with the ``Payment`` audit model.

    The ``tenant_id`` column gets a ``ForeignKey("tenants.id")`` reference
    only when ``app/models/tenant.py`` exists; otherwise it is a plain
    nullable UUID column.

    Args:
        dest: Absolute path for the new file.
        has_tenants: Whether ``app/models/tenant.py`` exists.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tenant_col = _PAYMENT_TENANT_COL_TENANTED if has_tenants else _PAYMENT_TENANT_COL_PLAIN
    content = _PAYMENT_MODEL_TEMPLATE.replace("TENANT_PLACEHOLDER", tenant_col)
    dest.write_text(content)


def _write_payment_schemas(dest: Path) -> None:
    """Write ``app/schemas/payment.py`` with Pydantic request/response schemas.

    ``PaymentPublic`` deliberately omits ``stripe_customer_id`` and
    ``metadata_json`` to avoid leaking PII via list endpoints.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_PAYMENT_SCHEMAS_TEMPLATE)


def _write_payment_crud(dest: Path) -> None:
    """Write ``app/crud/payment.py`` with async CRUD helpers.

    Every helper is keyed on the Stripe Checkout Session id (not the
    internal UUID) so that webhook handlers can reconcile events
    without a prior round trip.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_PAYMENT_CRUD_TEMPLATE)


def _write_payments_routes(dest: Path) -> None:
    """Write ``app/api/routes/payments.py`` with HTTP endpoints.

    Every route handler is kept ≤40 LOC by extracting helpers
    (``_build_line_items``, ``_owner_guard``, ``_handle_stripe_event``)
    that each fit in ≤50 LOC.  The webhook dispatcher uses
    ``stripe.Webhook.construct_event`` for signature verification.

    Args:
        dest: Absolute path for the new file.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_PAYMENTS_ROUTES_TEMPLATE)


def _write_payment_migration(versions_dir: Path, *, has_tenants: bool = False) -> Path:
    """Generate ``alembic/versions/add_stripe_checkout.py``.

    Uses ``find_migration_head`` to chain cleanly onto the existing
    Alembic head, avoiding the multi-root fork that hard-coded
    ``down_revision = "0001_initial"`` would cause when other adapt
    tools have already run.

    Args:
        versions_dir: Path to ``alembic/versions/`` directory.
        has_tenants: Whether multi-tenancy is installed.

    Returns:
        Path of the created migration file.
    """
    down_rev = find_migration_head(versions_dir) or "0001_initial"
    tenant_col = (
        _PAYMENT_MIGRATION_TENANT_TENANTED
        if has_tenants
        else _PAYMENT_MIGRATION_TENANT_PLAIN
    )
    content = (
        _PAYMENT_MIGRATION_TEMPLATE
        .replace("DOWN_REV", down_rev)
        .replace("TENANT_PLACEHOLDER", tenant_col)
    )
    migration_file = versions_dir / "add_stripe_checkout.py"
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


def _patch_config(
    config_file: Path,
    api_version: str,
    success_url: str,
    cancel_url: str,
) -> None:
    """Inject Stripe settings into the ``Settings`` class body.

    The fields must live INSIDE ``class Settings`` so pydantic-settings
    picks them up from env vars; appending at module level would create
    plain module attributes that the generated code can never reach.

    Args:
        config_file: Path to the existing ``app/core/config.py``.
        api_version: Value for ``STRIPE_API_VERSION`` default.
        success_url: Value for ``STRIPE_CHECKOUT_SUCCESS_URL`` default.
        cancel_url: Value for ``STRIPE_CHECKOUT_CANCEL_URL`` default.
    """
    src = config_file.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return

    block = (
        "\n"
        "    # --- Stripe payments — added by add_stripe_checkout tool ---\n"
        '    STRIPE_SECRET_KEY: str = ""\n'
        '    STRIPE_PUBLISHABLE_KEY: str = ""\n'
        '    STRIPE_WEBHOOK_SECRET: str = ""\n'
        f'    STRIPE_API_VERSION: str = "{api_version}"\n'
        f'    STRIPE_CHECKOUT_SUCCESS_URL: str = "{success_url}"\n'
        f'    STRIPE_CHECKOUT_CANCEL_URL: str = "{cancel_url}"\n'
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
    """Register the payments HTTP router in ``app/routes/__init__.py``.

    Idempotent — no-op if already present.

    Args:
        routes_init: Path to ``app/routes/__init__.py``.
    """
    _register_router_in_routes_init(
        routes_init,
        import_line="from app.api.routes.payments import router as payments_router",
        include_line="api_router.include_router(payments_router)",
    )


def _register_router_in_routes_init(
    routes_init: Path,
    *,
    import_line: str,
    include_line: str,
) -> None:
    """Idempotently add an import + ``api_router.include_router`` call.

    Copied verbatim from ``add_arq_worker`` to keep the tool suite
    consistent; callers should not re-implement router registration.

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


def _patch_env_example(env_example: Path) -> None:
    """Append Stripe env var documentation to ``.env.example``.

    Idempotent — no-op if ``STRIPE_SECRET_KEY`` already present.

    Args:
        env_example: Path to ``.env.example``.
    """
    src = env_example.read_text()
    if "STRIPE_SECRET_KEY" in src:
        return
    trailing = "" if src.endswith("\n") else "\n"
    block = (
        "\n"
        "# --- Stripe Checkout (add_stripe_checkout) ---\n"
        "STRIPE_SECRET_KEY=sk_test_...\n"
        "STRIPE_PUBLISHABLE_KEY=pk_test_...\n"
        "STRIPE_WEBHOOK_SECRET=whsec_...\n"
    )
    env_example.write_text(src + trailing + block)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _assert_parses(path: Path) -> None:
    """Raise ``SyntaxError`` if *path* is not valid Python.

    Args:
        path: Path to the file to validate.

    Raises:
        SyntaxError: If the file has a syntax error.
    """
    try:
        ast.parse(path.read_text())
    except SyntaxError as exc:
        raise SyntaxError(
            f"Generated file {path} has a syntax error: {exc}"
        ) from exc


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
# helper function stays well under the 50-LOC budget).  Each template uses
# plain string substitution via `.replace()`; no f-string brace escaping.
# ---------------------------------------------------------------------------

_STRIPE_CLIENT_TEMPLATE = textwrap.dedent("""\
    \"\"\"Stripe SDK wrapper — lazy import so the app boots without `stripe` installed.

    The Stripe Python library is imported INSIDE ``get_stripe()`` rather than
    at module import time.  This lets ``app.main`` be imported (and health-
    checked) on machines where the ``stripe`` package has not yet been
    ``pip install``-ed.  The helper is stateless: the SDK stores its API
    key and version on module globals, so calling ``get_stripe()`` repeatedly
    is a cheap attribute re-assignment.

    The secret key is read from ``settings.STRIPE_SECRET_KEY`` on every call
    and is NEVER logged or returned to a caller.
    \"\"\"
    from __future__ import annotations

    from typing import Any

    from app.core.config import settings


    def get_stripe() -> Any:
        \"\"\"Return the configured ``stripe`` SDK module.

        Imports the ``stripe`` package lazily, assigns the API key and
        version from ``settings``, and returns the module.  Callers should
        use the return value directly (e.g.
        ``stripe = get_stripe(); session = stripe.checkout.Session.create(...)``).

        Returns:
            The ``stripe`` module object with ``api_key`` and
            ``api_version`` configured from application settings.

        Raises:
            ModuleNotFoundError: If the ``stripe`` package is not installed.
        \"\"\"
        import stripe  # local import — keeps app.main importable without stripe

        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.api_version = settings.STRIPE_API_VERSION
        return stripe
""")


_PAYMENT_TENANT_COL_TENANTED = (
    '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
    '        Uuid,\n'
    '        ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    '        nullable=True,\n'
    '        index=True,\n'
    '        comment="Tenant owning this payment record",\n'
    '    )'
)

_PAYMENT_TENANT_COL_PLAIN = (
    '    tenant_id: Mapped[uuid.UUID | None] = mapped_column(\n'
    '        Uuid,\n'
    '        nullable=True,\n'
    '        index=True,\n'
    '        comment="Tenant owning this payment record",\n'
    '    )'
)


_PAYMENT_MODEL_TEMPLATE = textwrap.dedent("""\
    \"\"\"SQLAlchemy model for Stripe Checkout payment records.

    The ``payments`` table is the application's audit trail for every
    Stripe Checkout Session opened by a user.  A row is created in
    ``pending`` state when the session is opened and transitions to
    ``succeeded`` / ``failed`` / ``refunded`` / ``cancelled`` only via
    webhook confirmation from Stripe.  The client-side redirect to
    ``success_url`` is a UX hint, never a source of truth.

    Column name note: the JSON column is named ``metadata_json`` (not
    ``metadata``) because ``metadata`` is a reserved attribute on
    SQLAlchemy's declarative base.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime

    from sqlalchemy import (
        JSON,
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


    class Payment(Base):
        \"\"\"A Stripe Checkout Session record.

        Attributes:
            id: Internal UUID primary key.
            stripe_session_id: Stripe Checkout Session id (unique, index).
            stripe_payment_intent_id: Stripe PaymentIntent id (populated by
                webhook, indexed for reconciliation).
            stripe_customer_id: Stripe Customer id (PII — never exposed
                via ``PaymentPublic``).
            amount_cents: Amount in the smallest currency unit
                (e.g. US cents).
            currency: ISO 4217 three-letter currency code (uppercase).
            status: Lifecycle status string — one of ``pending``,
                ``succeeded``, ``failed``, ``refunded``, ``cancelled``.
            customer_email: Email captured from the Checkout Session.
            product_name: Human-readable product label.
            metadata_json: Free-form JSON metadata forwarded to Stripe.
            user_id: FK to ``users.id`` — the user who initiated the
                payment.  ``None`` for anonymous checkout.
            tenant_id: Optional tenant UUID (FK only when tenants table exists).
            created_at: UTC timestamp when the row was inserted.
            updated_at: UTC timestamp of the last change.
            succeeded_at: UTC timestamp when the payment cleared
                (``None`` until the success webhook lands).
        \"\"\"

        __tablename__ = "payments"

        id: Mapped[uuid.UUID] = mapped_column(
            Uuid, primary_key=True, default=uuid.uuid4
        )
        stripe_session_id: Mapped[str] = mapped_column(
            String(255), unique=True, nullable=False, index=True
        )
        stripe_payment_intent_id: Mapped[str | None] = mapped_column(
            String(255), nullable=True, index=True
        )
        stripe_customer_id: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
        currency: Mapped[str] = mapped_column(String(3), nullable=False)
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, server_default="pending"
        )
        customer_email: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        product_name: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
        user_id: Mapped[uuid.UUID | None] = mapped_column(
            Uuid,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        )
    TENANT_PLACEHOLDER
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
        succeeded_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )

        __table_args__ = (
            CheckConstraint(
                "status IN ('pending','succeeded','failed','refunded','cancelled')",
                name="ck_payments_status",
            ),
            Index(
                "ix_payments_status_created",
                "status",
                "created_at",
            ),
            Index(
                "ix_payments_user_created",
                "user_id",
                "created_at",
            ),
        )
""")


_PAYMENT_SCHEMAS_TEMPLATE = textwrap.dedent("""\
    \"\"\"Pydantic schemas for the Stripe Checkout payment flow.

    ``PaymentPublic`` deliberately omits ``stripe_customer_id``,
    ``stripe_session_id``, ``customer_email``, and ``metadata_json`` to
    avoid leaking PII via list endpoints.  Webhook handlers read the
    underlying ORM rows directly — they never round-trip through these
    schemas.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime
    from enum import Enum

    from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


    class PaymentStatus(str, Enum):
        \"\"\"Lifecycle status of a Stripe Checkout payment.

        Values:
            pending: Checkout Session opened, awaiting customer action.
            succeeded: Payment cleared (confirmed via webhook).
            failed: Async payment method declined.
            refunded: Payment fully or partially refunded via charge.refunded.
            cancelled: Customer abandoned checkout or session expired.
        \"\"\"

        pending = "pending"
        succeeded = "succeeded"
        failed = "failed"
        refunded = "refunded"
        cancelled = "cancelled"


    class CheckoutSessionCreate(BaseModel):
        \"\"\"Request body for POST /payments/checkout.

        Attributes:
            amount_cents: Unit amount in the smallest currency unit.
                Bounded ``> 0`` and ``<= 99_999_999`` to prevent overflow
                and to reject accidental zero-charges.
            currency: ISO 4217 three-letter currency code, uppercase.
            product_name: Human-readable product label shown in Checkout.
            quantity: Number of units purchased (1..999).
            customer_email: Optional email pre-filled on the Checkout page.
            success_url: Optional per-request override of the default
                redirect URL.
            cancel_url: Optional per-request override of the default
                cancel URL.
            metadata_json: Optional free-form metadata forwarded to Stripe
                as the Session ``metadata`` dict (max 50 keys).
        \"\"\"

        amount_cents: int = Field(gt=0, le=99_999_999)
        currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
        product_name: str = Field(min_length=1, max_length=255)
        quantity: int = Field(default=1, ge=1, le=999)
        customer_email: EmailStr | None = None
        success_url: HttpUrl | None = None
        cancel_url: HttpUrl | None = None
        metadata_json: dict[str, str] | None = Field(default=None, max_length=50)


    class CheckoutSessionResponse(BaseModel):
        \"\"\"Response body for POST /payments/checkout.

        Attributes:
            session_id: Stripe Checkout Session id.
            checkout_url: Hosted URL the client should redirect to.
            payment_id: Internal ``Payment.id`` UUID for later lookups.
        \"\"\"

        session_id: str
        checkout_url: str
        payment_id: uuid.UUID


    class PaymentPublic(BaseModel):
        \"\"\"PII-safe public view of a payment record.\"\"\"

        model_config = ConfigDict(from_attributes=True)

        id: uuid.UUID
        amount_cents: int
        currency: str
        status: PaymentStatus
        product_name: str | None = None
        created_at: datetime
        succeeded_at: datetime | None = None


    class PaymentListResponse(BaseModel):
        \"\"\"Envelope for GET /payments/me.

        Attributes:
            data: Page of public payment views.
            count: Total rows in the filtered query (NOT just the page).
        \"\"\"

        data: list[PaymentPublic]
        count: int
""")


_PAYMENT_CRUD_TEMPLATE = textwrap.dedent("""\
    \"\"\"Async CRUD helpers for the ``payments`` table.

    Every helper that transitions a payment through its lifecycle
    (pending → succeeded / failed / refunded) is keyed on the Stripe
    Checkout Session id, NOT the internal UUID.  This lets webhook
    handlers reconcile events without an intermediate lookup.
    \"\"\"
    from __future__ import annotations

    import uuid
    from datetime import datetime, timezone
    from typing import Any

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.payment import Payment


    async def create_pending_payment(
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None,
        amount_cents: int,
        currency: str,
        stripe_session_id: str,
        product_name: str | None,
        customer_email: str | None,
        metadata_json: dict[str, Any] | None,
    ) -> Payment:
        \"\"\"Insert a ``pending`` Payment row for a new Checkout Session.\"\"\"
        payment = Payment(
            user_id=user_id,
            amount_cents=amount_cents,
            currency=currency.upper(),
            stripe_session_id=stripe_session_id,
            product_name=product_name,
            customer_email=customer_email,
            metadata_json=metadata_json,
            status="pending",
        )
        session.add(payment)
        await session.flush()
        return payment


    async def mark_payment_succeeded(
        session: AsyncSession,
        *,
        stripe_session_id: str,
        payment_intent_id: str | None,
        stripe_customer_id: str | None,
    ) -> Payment | None:
        \"\"\"Transition a payment to ``succeeded`` (idempotent).\"\"\"
        payment = await get_payment_by_session_id(session, stripe_session_id)
        if payment is None or payment.status == "succeeded":
            return payment
        payment.status = "succeeded"
        payment.stripe_payment_intent_id = payment_intent_id
        payment.stripe_customer_id = stripe_customer_id
        payment.succeeded_at = datetime.now(timezone.utc)
        await session.flush()
        return payment


    async def mark_payment_failed(
        session: AsyncSession,
        *,
        stripe_session_id: str,
        reason: str,
    ) -> Payment | None:
        \"\"\"Transition a payment to ``failed`` (idempotent).\"\"\"
        payment = await get_payment_by_session_id(session, stripe_session_id)
        if payment is None or payment.status == "failed":
            return payment
        payment.status = "failed"
        # reason is attached to metadata so we never lose the audit trail
        md = dict(payment.metadata_json or {})
        md["failure_reason"] = reason[:500]
        payment.metadata_json = md
        await session.flush()
        return payment


    async def mark_payment_refunded(
        session: AsyncSession,
        *,
        stripe_session_id: str,
    ) -> Payment | None:
        \"\"\"Transition a payment to ``refunded`` (idempotent).\"\"\"
        payment = await get_payment_by_session_id(session, stripe_session_id)
        if payment is None or payment.status == "refunded":
            return payment
        payment.status = "refunded"
        await session.flush()
        return payment


    async def get_payment_by_session_id(
        session: AsyncSession,
        stripe_session_id: str,
    ) -> Payment | None:
        \"\"\"Return the Payment row with *stripe_session_id* or ``None``.\"\"\"
        stmt = select(Payment).where(
            Payment.stripe_session_id == stripe_session_id
        )
        return (await session.execute(stmt)).scalar_one_or_none()


    async def get_payment_by_id(
        session: AsyncSession,
        payment_id: uuid.UUID,
    ) -> Payment | None:
        \"\"\"Return the Payment row with *payment_id* or ``None``.\"\"\"
        stmt = select(Payment).where(Payment.id == payment_id)
        return (await session.execute(stmt)).scalar_one_or_none()


    async def list_user_payments(
        session: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Payment], int]:
        \"\"\"Return (rows, total_count) for a user's payments.\"\"\"
        total_stmt = (
            select(func.count())
            .select_from(Payment)
            .where(Payment.user_id == user_id)
        )
        total = int((await session.execute(total_stmt)).scalar_one() or 0)
        page_stmt = (
            select(Payment)
            .where(Payment.user_id == user_id)
            .order_by(Payment.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await session.execute(page_stmt)).scalars().all())
        return rows, total
""")


_PAYMENTS_ROUTES_TEMPLATE = textwrap.dedent("""\
    \"\"\"HTTP routes for the Stripe Checkout flow.

    Endpoints:
        POST /payments/checkout
            Create a Stripe Checkout Session and a pending Payment row.
            Requires authentication.

        GET /payments/{payment_id}
            Fetch a single Payment owned by the current user
            (superusers can fetch any).  Requires authentication.

        GET /payments/me
            Paginated list of the current user's payments.
            Requires authentication.

        POST /payments/webhook/stripe
            Stripe webhook receiver.  UNAUTHENTICATED by HTTP standards;
            the request is authenticated via the ``Stripe-Signature``
            header using ``stripe.Webhook.construct_event`` (HMAC-SHA256
            with a 5-minute replay window).
    \"\"\"
    from __future__ import annotations

    import logging
    import uuid
    from typing import Any

    from fastapi import APIRouter, HTTPException, Query, Request, status

    from app.api.deps import CurrentUser
    from app.core.config import settings
    from app.core.session import SessionDep
    from app.core.stripe_client import get_stripe
    from app.crud.payment import (
        create_pending_payment,
        get_payment_by_id,
        list_user_payments,
        mark_payment_failed,
        mark_payment_refunded,
        mark_payment_succeeded,
    )
    from app.schemas.payment import (
        CheckoutSessionCreate,
        CheckoutSessionResponse,
        PaymentListResponse,
        PaymentPublic,
    )

    logger = logging.getLogger(__name__)

    router = APIRouter(prefix="/payments", tags=["payments"])


    def _build_line_items(body: CheckoutSessionCreate) -> list[dict[str, Any]]:
        \"\"\"Build the Stripe Checkout ``line_items`` list from a request body.

        Extracted so the ``create_checkout_session`` handler stays small
        and so tests can exercise the line-item shape directly.
        \"\"\"
        return [
            {
                "price_data": {
                    "currency": body.currency.lower(),
                    "product_data": {"name": body.product_name},
                    "unit_amount": body.amount_cents,
                },
                "quantity": body.quantity,
            }
        ]


    def _resolve_urls(body: CheckoutSessionCreate) -> tuple[str, str]:
        \"\"\"Resolve success/cancel URLs, falling back to settings defaults.\"\"\"
        success = str(body.success_url) if body.success_url else settings.STRIPE_CHECKOUT_SUCCESS_URL
        cancel = str(body.cancel_url) if body.cancel_url else settings.STRIPE_CHECKOUT_CANCEL_URL
        return success, cancel


    @router.post(
        "/checkout",
        response_model=CheckoutSessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_checkout_session(
        body: CheckoutSessionCreate,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> CheckoutSessionResponse:
        \"\"\"Create a Stripe Checkout Session + pending Payment row.\"\"\"
        stripe = get_stripe()
        success_url, cancel_url = _resolve_urls(body)
        try:
            checkout = stripe.checkout.Session.create(
                mode="payment",
                line_items=_build_line_items(body),
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=body.customer_email,
                metadata=body.metadata_json or {},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("stripe checkout session create failed")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="stripe checkout session create failed",
            ) from exc
        payment = await create_pending_payment(
            session,
            user_id=current_user.id,
            amount_cents=body.amount_cents,
            currency=body.currency,
            stripe_session_id=checkout.id,
            product_name=body.product_name,
            customer_email=body.customer_email,
            metadata_json=body.metadata_json,
        )
        await session.commit()
        return CheckoutSessionResponse(
            session_id=checkout.id,
            checkout_url=checkout.url,
            payment_id=payment.id,
        )


    def _owner_guard(payment, current_user) -> None:
        \"\"\"Raise 404 unless *current_user* owns *payment* (or is superuser).\"\"\"
        is_superuser = getattr(current_user, "is_superuser", False)
        if is_superuser:
            return
        if payment.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="payment not found",
            )


    @router.get("/me", response_model=PaymentListResponse)
    async def list_my_payments(
        current_user: CurrentUser,
        session: SessionDep,
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> PaymentListResponse:
        \"\"\"Return the current user's payments, newest first.\"\"\"
        rows, total = await list_user_payments(
            session, current_user.id, limit=limit, offset=skip
        )
        data = [PaymentPublic.model_validate(r) for r in rows]
        return PaymentListResponse(data=data, count=total)


    @router.get("/{payment_id}", response_model=PaymentPublic)
    async def get_payment(
        payment_id: uuid.UUID,
        current_user: CurrentUser,
        session: SessionDep,
    ) -> PaymentPublic:
        \"\"\"Fetch a single Payment owned by the current user.\"\"\"
        payment = await get_payment_by_id(session, payment_id)
        if payment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="payment not found",
            )
        _owner_guard(payment, current_user)
        return PaymentPublic.model_validate(payment)


    async def _handle_stripe_event(
        session,
        event: dict[str, Any],
    ) -> None:
        \"\"\"Dispatch a verified Stripe event to the right CRUD transition.

        Unknown event types are silently acked.  Each branch is
        idempotent — second deliveries of the same event are safe.
        \"\"\"
        event_type = event.get("type", "")
        data = event.get("data", {}).get("object", {}) or {}
        session_id = data.get("id") or data.get("payment_intent") or ""
        if not session_id:
            return
        if event_type in ("checkout.session.completed",
                          "checkout.session.async_payment_succeeded"):
            await mark_payment_succeeded(
                session,
                stripe_session_id=session_id,
                payment_intent_id=data.get("payment_intent"),
                stripe_customer_id=data.get("customer"),
            )
        elif event_type == "checkout.session.async_payment_failed":
            reason = (data.get("last_payment_error") or {}).get("message", "payment failed")
            await mark_payment_failed(
                session,
                stripe_session_id=session_id,
                reason=str(reason),
            )
        elif event_type == "charge.refunded":
            # For charge.refunded the session id lives on the charge's
            # payment_intent metadata — callers must set metadata[session_id]
            # when creating the Checkout Session if they need refund linkage.
            linked = (data.get("metadata") or {}).get("session_id", "")
            if linked:
                await mark_payment_refunded(session, stripe_session_id=linked)


    @router.post("/webhook/stripe")
    async def stripe_webhook(
        request: Request,
        session: SessionDep,
    ) -> dict[str, bool]:
        \"\"\"Receive and verify a Stripe webhook, then dispatch the event.\"\"\"
        payload = await request.body()
        sig_header = request.headers.get("stripe-signature", "")
        stripe = get_stripe()
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except Exception as exc:  # noqa: BLE001 — SDK raises multiple types
            logger.warning("stripe webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid stripe signature",
            ) from exc
        await _handle_stripe_event(session, event)
        await session.commit()
        return {"received": True}
""")


_PAYMENT_MIGRATION_TENANT_TENANTED = (
    '        sa.Column(\n'
    '            "tenant_id", sa.Uuid(),\n'
    '            sa.ForeignKey("tenants.id", ondelete="SET NULL"),\n'
    '            nullable=True,\n'
    '        ),'
)

_PAYMENT_MIGRATION_TENANT_PLAIN = (
    '        sa.Column("tenant_id", sa.Uuid(), nullable=True),'
)


_PAYMENT_MIGRATION_TEMPLATE = textwrap.dedent("""\
    \"\"\"Add payments table for Stripe Checkout.

    Revision ID: add_stripe_checkout
    Revises: DOWN_REV
    Create Date: auto-generated by add_stripe_checkout tool
    \"\"\"
    from __future__ import annotations

    import sqlalchemy as sa
    from alembic import op

    revision = "add_stripe_checkout"
    down_revision = "DOWN_REV"
    branch_labels = None
    depends_on = None


    def _payment_columns() -> list:
        \"\"\"Return the column list for the payments table.

        Extracted so ``upgrade()`` stays well under the 50-LOC budget.
        \"\"\"
        return [
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column(
                "stripe_session_id", sa.String(255),
                nullable=False, unique=True,
            ),
            sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
            sa.Column("stripe_customer_id", sa.String(255), nullable=True),
            sa.Column("amount_cents", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(3), nullable=False),
            sa.Column(
                "status", sa.String(32),
                server_default="pending", nullable=False,
            ),
            sa.Column("customer_email", sa.String(255), nullable=True),
            sa.Column("product_name", sa.String(255), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column(
                "user_id", sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
    TENANT_PLACEHOLDER
            sa.Column(
                "created_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True),
                server_default=sa.func.now(), nullable=False,
            ),
            sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('pending','succeeded','failed','refunded','cancelled')",
                name="ck_payments_status",
            ),
        ]


    def _create_payment_indexes() -> None:
        \"\"\"Create all indexes on the payments table.\"\"\"
        op.create_index(
            "ix_payments_stripe_session_id",
            "payments", ["stripe_session_id"], unique=True,
        )
        op.create_index(
            "ix_payments_stripe_payment_intent_id",
            "payments", ["stripe_payment_intent_id"],
        )
        op.create_index("ix_payments_user_id", "payments", ["user_id"])
        op.create_index(
            "ix_payments_status_created",
            "payments", ["status", sa.text("created_at DESC")],
        )
        op.create_index(
            "ix_payments_user_created",
            "payments", ["user_id", sa.text("created_at DESC")],
        )


    def upgrade() -> None:
        \"\"\"Create the payments table and all indexes.\"\"\"
        op.create_table("payments", *_payment_columns())
        _create_payment_indexes()


    def downgrade() -> None:
        \"\"\"Drop the payments table and its indexes.\"\"\"
        op.drop_index("ix_payments_user_created", table_name="payments")
        op.drop_index("ix_payments_status_created", table_name="payments")
        op.drop_index("ix_payments_user_id", table_name="payments")
        op.drop_index(
            "ix_payments_stripe_payment_intent_id", table_name="payments"
        )
        op.drop_index(
            "ix_payments_stripe_session_id", table_name="payments"
        )
        op.drop_table("payments")
""")
