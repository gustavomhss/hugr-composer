# TOOL-054: add_stripe_checkout

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_stripe_checkout` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2, Stripe SDK (optional at boot) |
| Signature | `add_stripe_checkout(inp: ToolInput, *, api_version: str = "2024-06-20", success_url: str = "http://localhost:8000/success", cancel_url: str = "http://localhost:8000/cancel") -> ToolResult` |
| Parameters | `inp.project_dir`: Absolute path to FastAPI project root<br>`inp.dry_run`: If `True`, plan only; write nothing<br>`api_version`: Stripe API version pin (default `"2024-06-20"`) — maps to `settings.STRIPE_API_VERSION`<br>`success_url`: Default Stripe redirect after successful checkout (default `"http://localhost:8000/success"`) — maps to `settings.STRIPE_CHECKOUT_SUCCESS_URL`<br>`cancel_url`: Default Stripe redirect after cancelled checkout (default `"http://localhost:8000/cancel"`) — maps to `settings.STRIPE_CHECKOUT_CANCEL_URL` |
| Files created | ≥ 5 (`app/core/stripe_client.py`, `app/models/payment.py`, `app/schemas/payment.py`, `app/crud/payment.py`, `app/api/routes/payments.py`, `alembic/versions/add_stripe_checkout.py`) |
| Files modified | ≥ 2 (`app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py`, `requirements.txt`, `.env.example`) |

The `fastapi_add_stripe_checkout` tool installs a production-grade Stripe
Checkout flow into a FastAPI project: a lazy SDK wrapper, a `Payment`
SQLAlchemy model (tenant-aware when `app/models/tenant.py` exists), Pydantic
request/response schemas that deliberately omit PII, async CRUD helpers keyed
on the Stripe Checkout Session id, HTTP routes for creating a Checkout
Session, fetching a single payment, listing the current user's payments, and
a signature-verified webhook receiver that terminates
`checkout.session.completed`, `checkout.session.async_payment_succeeded`,
`checkout.session.async_payment_failed`, and `charge.refunded` events
idempotently, plus an Alembic migration and every required `settings` field.

---

## 2. Purpose

Three problems kill Stripe integrations in production, and every one of them
shows up in the first review of a hand-written checkout flow:

**Problem 1 — PCI scope blow-up.** Teams reach for the `PaymentIntent` SDK
because it "feels more integrated", attach a card-element iframe to their own
domain, and immediately fall into PCI DSS SAQ D — the heaviest compliance tier,
requiring quarterly ASV scans, penetration testing, a documented information
security programme, and a dedicated Qualified Security Assessor for most
merchants. A single POST that touches a PAN in the request body, even
transiently, is enough. The fix is Stripe's **hosted Checkout Sessions**: the
customer is redirected to a Stripe-owned domain, the card number never crosses
the application boundary, and the merchant collapses from SAQ D to SAQ A — a
one-page self-assessment questionnaire. Checkout also handles 3DS2 / SCA,
Apple Pay, Google Pay, Klarna, and Link with zero extra code.

**Problem 2 — Webhook signature verification done wrong (or not at all).**
The canonical failure mode is a `POST /webhook/stripe` handler that reads
`request.json()`, dispatches on `event["type"]`, and writes to the database.
An attacker who knows the endpoint URL can forge a `checkout.session.completed`
event with any `payment_intent` and any `amount`, and the handler will happily
mark payments as succeeded. The fix is non-negotiable: every webhook delivery
MUST pass through `stripe.Webhook.construct_event(payload, sig_header,
STRIPE_WEBHOOK_SECRET)`, which verifies the HMAC-SHA256 signature in the
`Stripe-Signature` header against the raw request body and enforces a
5-minute timestamp tolerance for replay protection. A
`SignatureVerificationError` MUST return HTTP 400 BEFORE any database write,
BEFORE any logging that echoes the payload, and BEFORE any side effect.

**Problem 3 — Idempotency done wrong.** Stripe retries webhook deliveries on
any non-2xx response (and sometimes on 2xx timeouts) with exponential backoff
up to three days. Any webhook handler that is not idempotent will double-mark
payments, double-credit accounts, and double-fire downstream events the moment
a deploy coincides with a retry storm. The naive fix ("check a processed-event
table before writing") introduces a TOCTOU race that two concurrent workers
can lose. The correct fix is state-based idempotency at the CRUD layer: every
lifecycle transition (`pending → succeeded`, `pending → failed`, `* →
refunded`) reads the current row, short-circuits if it is already in the
target state, and writes through a single atomic UPDATE. The Stripe Checkout
Session id is the natural stable key.

**Solution — this tool.** It generates the whole kit in one pass:

1. **Lazy SDK import.** `app/core/stripe_client.py` exposes `get_stripe()`
   which imports the `stripe` module INSIDE the function body so the
   application can boot, be imported in tests, and run health checks on a
   machine where `stripe` has not been `pip install`-ed. The tool still appends
   `stripe>=11.0.0` to `requirements.txt` — the lazy import is a robustness
   belt, not a licence to skip installation in production. The secret key is
   read from `settings.STRIPE_SECRET_KEY` on every call and is NEVER logged or
   returned to a caller.
2. **Stateful audit model.** `app/models/payment.py` defines a `Payment` row
   that is created in `pending` state when the Checkout Session opens and
   transitions to `succeeded` / `failed` / `refunded` / `cancelled` ONLY via
   signed webhook confirmation. The client-side redirect to `success_url` is
   a UX hint, never a source of truth — and the tool's docstring says so.
3. **PII-safe public schema.** `PaymentPublic` in `app/schemas/payment.py`
   deliberately omits `stripe_customer_id`, `stripe_session_id`,
   `customer_email`, and `metadata_json`. The tests assert this at runtime by
   slicing the `PaymentPublic` class body out of the file and grep-ing for the
   forbidden field names. Webhook handlers read ORM rows directly; they never
   round-trip through these schemas.
4. **Signature-verified webhook.** `app/api/routes/payments.py` terminates the
   Stripe webhook via `stripe.Webhook.construct_event`; any verification
   failure raises HTTP 400 BEFORE the dispatch helper runs. Unknown event
   types are silently acked with HTTP 200 so Stripe stops retrying.
5. **Idempotent CRUD.** `app/crud/payment.py` exposes
   `mark_payment_succeeded` / `mark_payment_failed` / `mark_payment_refunded`
   — each keyed on the Stripe session id, each a no-op when the row is
   already in the target state.
6. **Tight function budget.** Every helper in the generated `app/` stays
   below 50 lines of code. The migration's `upgrade()` in particular was
   refactored to ≤ 10 LOC by extracting `_payment_columns()` (column list)
   and `_create_payment_indexes()` (five CREATE INDEX calls) into
   module-level helpers. The test harness walks the AST and fails the build
   if any generated function breaks the budget.

This tool is idempotent: a second run detects the `get_stripe` fingerprint in
`app/core/stripe_client.py`, returns `status="no_op"`, and touches no files.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 3 s | Must run in CI without blocking; measured as `execution_time_ms > 0` in T-19 |
| Files created on first run | ≥ 5 | Complete Stripe kit requires client, model, schemas, CRUD, routes, migration |
| Files modified on first run | ≥ 2 | Config, models init, routes init, requirements must be patched |
| Idempotent second run | Zero files touched | `status="no_op"`, empty `files_created`, empty `files_modified` (T-02) |
| Max generated function LOC | ≤ 50 | AST walk over `app/` enforces the budget (T-07) |
| Webhook signature verification | `< 10 ms` | Pure HMAC-SHA256; Stripe SDK ships an optimised C path |
| Checkout session creation latency | `< 600 ms` p95 | Dominated by the outbound Stripe API call |
| Webhook replay window | 5 minutes | Stripe-enforced tolerance inside `construct_event` |
| Migration runtime | `< 100 ms` | Single `CREATE TABLE` + 5 `CREATE INDEX` on an empty table |
| Max body size for webhook | 64 KiB (FastAPI default) | Stripe events are far below this — tighten per deployment if needed |

---

## 4. Code Examples (Before / After)

### 4.1 Stripe SDK wrapper — BEFORE

The hand-written version eagerly imports `stripe` at module load time, which
makes the entire `app` package fail to import on a machine where `stripe` is
not installed (test runners, docs builds, cold Lambda containers). It also
reads `settings.STRIPE_SECRET_KEY` exactly once, so rotating the key requires
a process restart.

```python
# app/core/stripe_client.py — BEFORE (anti-pattern)
import stripe  # hard fail if `stripe` not installed

from app.core.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY
stripe.api_version = "2024-06-20"


def get_stripe():
    return stripe
```

### 4.2 Stripe SDK wrapper — AFTER

Lazy import + per-call key assignment + no module-level side effects.
Generated verbatim by `_STRIPE_CLIENT_TEMPLATE`.

```python
# app/core/stripe_client.py — AFTER (from _STRIPE_CLIENT_TEMPLATE)
"""Stripe SDK wrapper — lazy import so the app boots without `stripe` installed.

The Stripe Python library is imported INSIDE ``get_stripe()`` rather than
at module import time.  This lets ``app.main`` be imported (and health-
checked) on machines where the ``stripe`` package has not yet been
``pip install``-ed.  The helper is stateless: the SDK stores its API
key and version on module globals, so calling ``get_stripe()`` repeatedly
is a cheap attribute re-assignment.

The secret key is read from ``settings.STRIPE_SECRET_KEY`` on every call
and is NEVER logged or returned to a caller.
"""
from __future__ import annotations

from typing import Any

from app.core.config import settings


def get_stripe() -> Any:
    """Return the configured ``stripe`` SDK module.

    Imports the ``stripe`` package lazily, assigns the API key and
    version from ``settings``, and returns the module.  Callers should
    use the return value directly (e.g.
    ``stripe = get_stripe(); session = stripe.checkout.Session.create(...)``).

    Returns:
        The ``stripe`` module object with ``api_key`` and
        ``api_version`` configured from application settings.

    Raises:
        ModuleNotFoundError: If the ``stripe`` package is not installed.
    """
    import stripe  # local import — keeps app.main importable without stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    return stripe
```

### 4.3 Checkout session creation — BEFORE

The typical hand-written handler writes the payment row AFTER the Stripe call
succeeds, which means a crash between the two calls leaves a session without
any audit trail in the application database. It also leaks the secret key
through exception logging because the SDK exception is not sanitised.

```python
# app/api/routes/payments.py — BEFORE (anti-pattern)
@router.post("/checkout")
async def create_checkout(body: CheckoutSessionCreate, user=Depends(current_user)):
    session = stripe.checkout.Session.create(  # raises on auth failure — logs the key
        mode="payment",
        line_items=[{"price_data": {"currency": body.currency, ...}, "quantity": 1}],
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    # If the process dies here, we have a Stripe session with no DB record.
    payment = Payment(stripe_session_id=session.id, amount_cents=body.amount_cents, ...)
    db.add(payment)
    await db.commit()
    return {"url": session.url}
```

### 4.4 Checkout session creation — AFTER

From `_PAYMENTS_ROUTES_TEMPLATE`. The handler extracts `_build_line_items`
and `_resolve_urls` so it stays well under 50 LOC; it raises a sanitised
HTTP 502 on SDK failure (no payload echo); the pending `Payment` row is
flushed in the SAME transaction that issues the `session.commit()` after
Stripe responds, so a crash between the Stripe call and the DB write leaves
a retryable Stripe session and a pending audit row.

```python
# app/api/routes/payments.py — AFTER (from _PAYMENTS_ROUTES_TEMPLATE)
def _build_line_items(body: CheckoutSessionCreate) -> list[dict[str, Any]]:
    """Build the Stripe Checkout ``line_items`` list from a request body."""
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
    """Resolve success/cancel URLs, falling back to settings defaults."""
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
    """Create a Stripe Checkout Session + pending Payment row."""
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
```

### 4.5 Webhook handler with signature verification — BEFORE

The typical naive webhook handler. Note the missing signature check, the
direct dispatch on untrusted input, and the use of `request.json()` which
silently UTF-8-decodes the raw body (a subtle bug: Stripe's HMAC is computed
over the raw bytes, so any re-encoding round trip breaks signature
verification — another reason the signed version reads `await
request.body()`).

```python
# app/api/routes/payments.py — BEFORE (anti-pattern)
@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    event = await request.json()          # UNSAFE — no signature verification
    if event["type"] == "checkout.session.completed":
        session_id = event["data"]["object"]["id"]
        await mark_payment_succeeded(db, stripe_session_id=session_id, ...)
    return {"ok": True}
```

### 4.6 Webhook handler — AFTER

From `_PAYMENTS_ROUTES_TEMPLATE`. Three defences: raw bytes via
`await request.body()`, signature verification via
`stripe.Webhook.construct_event`, and idempotent dispatch via
`_handle_stripe_event`. Signature failure raises HTTP 400 BEFORE any DB work.

```python
# app/api/routes/payments.py — AFTER (from _PAYMENTS_ROUTES_TEMPLATE)
async def _handle_stripe_event(
    session,
    event: dict[str, Any],
) -> None:
    """Dispatch a verified Stripe event to the right CRUD transition.

    Unknown event types are silently acked.  Each branch is
    idempotent — second deliveries of the same event are safe.
    """
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
        linked = (data.get("metadata") or {}).get("session_id", "")
        if linked:
            await mark_payment_refunded(session, stripe_session_id=linked)


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    session: SessionDep,
) -> dict[str, bool]:
    """Receive and verify a Stripe webhook, then dispatch the event."""
    payload = await request.body()                        # raw bytes for HMAC
    sig_header = request.headers.get("stripe-signature", "")
    stripe = get_stripe()
    try:
        event = stripe.Webhook.construct_event(           # HMAC + replay check
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except Exception as exc:  # noqa: BLE001 — SDK raises multiple types
        logger.warning("stripe webhook signature verification failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid stripe signature",
        ) from exc
    await _handle_stripe_event(session, event)            # idempotent dispatch
    await session.commit()
    return {"received": True}
```

### 4.7 Payment SQLAlchemy model — AFTER

From `_PAYMENT_MODEL_TEMPLATE`. Note the `CheckConstraint` bounding the
status column, the composite indexes for the two dominant list queries, and
the deliberate column name `metadata_json` (because `metadata` is reserved
on SQLAlchemy's declarative base).

```python
# app/models/payment.py — AFTER (from _PAYMENT_MODEL_TEMPLATE)
class Payment(Base):
    """A Stripe Checkout Session record.

    Attributes:
        id: Internal UUID primary key.
        stripe_session_id: Stripe Checkout Session id (unique, index).
        stripe_payment_intent_id: Stripe PaymentIntent id (populated by
            webhook, indexed for reconciliation).
        stripe_customer_id: Stripe Customer id (PII — never exposed
            via ``PaymentPublic``).
        amount_cents: Amount in the smallest currency unit (e.g. US cents).
        currency: ISO 4217 three-letter currency code (uppercase).
        status: Lifecycle status string — one of ``pending``,
            ``succeeded``, ``failed``, ``refunded``, ``cancelled``.
        customer_email: Email captured from the Checkout Session.
        product_name: Human-readable product label.
        metadata_json: Free-form JSON metadata forwarded to Stripe.
        user_id: FK to ``users.id``.
        tenant_id: Optional tenant UUID (FK only when tenants table exists).
        created_at: UTC timestamp when the row was inserted.
        updated_at: UTC timestamp of the last change.
        succeeded_at: UTC timestamp when the payment cleared.
    """

    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
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
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # tenant_id column injected when app/models/tenant.py exists
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
        Index("ix_payments_status_created", "status", "created_at"),
        Index("ix_payments_user_created", "user_id", "created_at"),
    )
```

### 4.8 PII-safe schemas — AFTER

From `_PAYMENT_SCHEMAS_TEMPLATE`. `PaymentPublic` omits the four PII fields
(`stripe_customer_id`, `stripe_session_id`, `customer_email`,
`metadata_json`) and the tests slice the class body out of the file to
verify it at runtime (see CC-17).

```python
# app/schemas/payment.py — AFTER (from _PAYMENT_SCHEMAS_TEMPLATE)
class PaymentStatus(str, Enum):
    """Lifecycle status of a Stripe Checkout payment."""
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    refunded = "refunded"
    cancelled = "cancelled"


class CheckoutSessionCreate(BaseModel):
    """Request body for POST /payments/checkout."""
    amount_cents: int = Field(gt=0, le=99_999_999)
    currency: str = Field(min_length=3, max_length=3, pattern="^[A-Z]{3}$")
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(default=1, ge=1, le=999)
    customer_email: EmailStr | None = None
    success_url: HttpUrl | None = None
    cancel_url: HttpUrl | None = None
    metadata_json: dict[str, str] | None = Field(default=None, max_length=50)


class CheckoutSessionResponse(BaseModel):
    """Response body for POST /payments/checkout."""
    session_id: str
    checkout_url: str
    payment_id: uuid.UUID


class PaymentPublic(BaseModel):
    """PII-safe public view of a payment record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount_cents: int
    currency: str
    status: PaymentStatus
    product_name: str | None = None
    created_at: datetime
    succeeded_at: datetime | None = None
    # EXPLICITLY NOT EXPOSED: stripe_customer_id, stripe_session_id,
    # customer_email, metadata_json. This is INV-PAY-02 and is enforced
    # by CC-17 at test time.


class PaymentListResponse(BaseModel):
    """Envelope for GET /payments/me."""
    data: list[PaymentPublic]
    count: int
```

### 4.9 Idempotent CRUD — AFTER

From `_PAYMENT_CRUD_TEMPLATE`. Every state transition short-circuits if the
row is already in the target state; the Stripe session id is the stable key.

```python
# app/crud/payment.py — AFTER (from _PAYMENT_CRUD_TEMPLATE)
async def mark_payment_succeeded(
    session: AsyncSession,
    *,
    stripe_session_id: str,
    payment_intent_id: str | None,
    stripe_customer_id: str | None,
) -> Payment | None:
    """Transition a payment to ``succeeded`` (idempotent)."""
    payment = await get_payment_by_session_id(session, stripe_session_id)
    if payment is None or payment.status == "succeeded":
        return payment                                     # idempotent no-op
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
    """Transition a payment to ``failed`` (idempotent)."""
    payment = await get_payment_by_session_id(session, stripe_session_id)
    if payment is None or payment.status == "failed":
        return payment                                     # idempotent no-op
    payment.status = "failed"
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
    """Transition a payment to ``refunded`` (idempotent)."""
    payment = await get_payment_by_session_id(session, stripe_session_id)
    if payment is None or payment.status == "refunded":
        return payment                                     # idempotent no-op
    payment.status = "refunded"
    await session.flush()
    return payment
```

### 4.10 Migration — AFTER

The `upgrade()` body is tiny because all the real work lives in
`_payment_columns()` and `_create_payment_indexes()`. This is a deliberate
refactor driven by the ≤ 50 LOC budget (T-07) — the previous version of this
tool had a 90-line `upgrade()` that tripped the budget test.

```python
# alembic/versions/add_stripe_checkout.py — AFTER (from _PAYMENT_MIGRATION_TEMPLATE)
def _payment_columns() -> list:
    """Return the column list for the payments table.

    Extracted so ``upgrade()`` stays well under the 50-LOC budget.
    """
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stripe_session_id", sa.String(255), nullable=False, unique=True),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("customer_email", sa.String(255), nullable=True),
        sa.Column("product_name", sa.String(255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "user_id", sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # tenant_id column placeholder (injected per project)
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
    """Create all indexes on the payments table."""
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
    """Create the payments table and all indexes."""
    op.create_table("payments", *_payment_columns())
    _create_payment_indexes()


def downgrade() -> None:
    """Drop the payments table and its indexes."""
    op.drop_index("ix_payments_user_created", table_name="payments")
    op.drop_index("ix_payments_status_created", table_name="payments")
    op.drop_index("ix_payments_user_id", table_name="payments")
    op.drop_index("ix_payments_stripe_payment_intent_id", table_name="payments")
    op.drop_index("ix_payments_stripe_session_id", table_name="payments")
    op.drop_table("payments")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Webhook signature verification is mandatory** | `stripe_webhook` route calls `stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)` BEFORE any DB work; verification failure raises HTTP 400 (INV-PAY-01, T-14) |
| QS-2 | **Raw request bytes used for signature** | Webhook reads `await request.body()`, not `request.json()` — HMAC is computed over raw bytes and any re-encoding breaks verification |
| QS-3 | **PaymentPublic never leaks PII** | `PaymentPublic` schema body deliberately omits `stripe_customer_id`, `stripe_session_id`, `customer_email`, `metadata_json`; verified at runtime by slicing the class body and grep-ing the forbidden field names (INV-PAY-02, T-17) |
| QS-4 | **Stripe SDK is imported lazily** | `get_stripe()` does `import stripe` INSIDE the function body; `app.main` imports cleanly on machines without the `stripe` package (T-11) |
| QS-5 | **Main.py does not import stripe** | `app/main.py` is NOT patched by this tool; Stripe SDK is stateless and needs no lifespan hook (T-16) |
| QS-6 | **Every CRUD transition is idempotent** | `mark_payment_succeeded` / `mark_payment_failed` / `mark_payment_refunded` short-circuit if the row is already in the target state — second webhook deliveries are safe (INV-PAY-03) |
| QS-7 | **Payment row is the single source of truth** | Status transitions occur ONLY via signed webhook confirmation; client-side redirect to `success_url` is a UX hint, never persisted as state |
| QS-8 | **Status column is constrained at the DB level** | `CheckConstraint("status IN ('pending','succeeded','failed','refunded','cancelled')")` prevents invalid writes even if application code is compromised |
| QS-9 | **Amount is integer cents, never float** | `amount_cents: int = Field(gt=0, le=99_999_999)` in `CheckoutSessionCreate`; column type `Integer` in `Payment`; currency is an ISO 4217 uppercase code |
| QS-10 | **Unknown event types are silently acked** | `_handle_stripe_event` has no `else` branch — unrecognised event types return HTTP 200 so Stripe stops retrying |
| QS-11 | **Stripe API version is pinned in settings** | `STRIPE_API_VERSION` defaults to `"2024-06-20"`; applied on every `get_stripe()` call; protects against silent breaking changes |
| QS-12 | **Every generated function ≤ 50 LOC** | AST walk over `app/` after generation; the test `test_no_function_over_50_loc` fails the build if any function exceeds the budget (T-07) |
| QS-13 | **Migration `upgrade()` ≤ 10 LOC** | `upgrade()` delegates to `_payment_columns()` + `_create_payment_indexes()` so its body is five lines long (part of QS-12 enforcement) |
| QS-14 | **All generated Python files AST-parse** | Tool calls `_assert_parses(p)` on every created `.py`; post-generation the test harness re-walks the tree and asserts `ast.parse(f.read_text())` (T-06) |
| QS-15 | **Tool is idempotent** | Fingerprint check on `get_stripe` in `stripe_client.py` short-circuits the second run to `status="no_op"` with zero file touches (T-02) |
| QS-16 | **Dry-run writes nothing** | `dry_run=True` returns `success` with empty `files_created` / `files_modified` and identical before/after snapshots of all `.py` files (T-03) |
| QS-17 | **Secret key is never logged** | Webhook signature failure log is `"stripe webhook signature verification failed"` — no payload echo, no header echo, no key echo; checkout failure log is `"stripe checkout session create failed"` for the same reason |

---

## 6. Completeness Criteria

Each CC maps directly to an assertion in
`tests/test_add_stripe_checkout.py`. The 20 test functions enumerated in the
file's `__main__` block are the authoritative source; this table is
generated from them.

| ID | Criterion | Test function | Verification |
|----|-----------|--------------|--------------|
| CC-01 | Tool returns `status="success"` on a fresh project | `test_success_status` | `assert result.status == "success"` |
| CC-02 | Second run is idempotent (`status="no_op"`, zero files touched) | `test_idempotent` | `assert r2.status == "no_op"`; `assert not r2.files_created`; `assert not r2.files_modified` |
| CC-03 | `dry_run=True` writes zero files | `test_dry_run` | Pre/post snapshot of every `.py` file is byte-identical; `result.files_created` empty; `result.files_modified` empty |
| CC-04 | ≥ 5 files created on first run | `test_files_created_count` | `assert len(result.files_created) >= 5`; each path exists on disk |
| CC-05 | ≥ 2 files modified on first run | `test_files_modified_count` | `assert len(result.files_modified) >= 2`; each path exists on disk |
| CC-06 | Every generated `.py` AST-parses | `test_all_py_parse` | `ast.parse(f.read_text())` succeeds for every `*.py` under `project_dir` |
| CC-07 | No function in generated `app/` exceeds 50 LOC | `test_no_function_over_50_loc` | AST walk; `(end_lineno - lineno + 1) <= 50` for every `FunctionDef` / `AsyncFunctionDef` |
| CC-08 | All 6 `STRIPE_*` config fields are present AND inside the `Settings` class body | `test_config_fields_patched` | `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_API_VERSION`, `STRIPE_CHECKOUT_SUCCESS_URL`, `STRIPE_CHECKOUT_CANCEL_URL` present; first match starts with 4-space indent (class body) |
| CC-09 | `Payment` registered in `app/models/__init__.py` | `test_models_init_patched` | `"Payment" in content` |
| CC-10 | `payment` router registered in `app/routes/__init__.py` | `test_routes_registered` | `"payment" in content.lower()` when the file exists |
| CC-11 | `app/core/stripe_client.py` exists with lazy `get_stripe` | `test_stripe_client_lazy_import` | File exists; `"get_stripe" in content`; `"import stripe" in content` |
| CC-12 | `app/models/payment.py` exists with `class Payment` | `test_payment_model_created` | File exists; `"class Payment" in content` |
| CC-13 | `app/crud/payment.py` has ≥ 5 async CRUD helpers | `test_payment_crud_created` | File exists; `content.count("async def ") >= 5` |
| CC-14 | `app/api/routes/payments.py` contains the Stripe webhook route | `test_webhook_route_present` | File exists; `"webhook" in content.lower()`; `"stripe" in content.lower()` |
| CC-15 | All 6 `STRIPE_*` fields present in `config.py` | `test_stripe_config_fields` | Same 6 fields as CC-08, re-verified independently from a fresh fixture |
| CC-16 | `app/main.py` does NOT import stripe or reference stripe_client | `test_main_not_patched` | `"import stripe" not in content`; `"stripe_client" not in content` |
| CC-17 | `PaymentPublic` schema body omits `stripe_customer_id` AND `customer_email` | `test_pii_safe_schema` | Class body sliced between `"class PaymentPublic"` and next `"\nclass "`; `"stripe_customer_id" not in public_body`; `"customer_email" not in public_body` |
| CC-18 | `stripe>=` is in `requirements.txt` | `test_requirements_stripe` | `"stripe>=" in requirements.read_text()` |
| CC-19 | `execution_time_ms` is positive | `test_execution_time_recorded` | `assert result.execution_time_ms > 0` |
| CC-20 | After two runs every `.py` file still parses | `test_idempotent_project_still_parses` | Tool invoked twice; AST walk over every `.py` succeeds |

**Test file**: `adapt/extend/infrastructure/test_add_stripe_checkout.py`
(20 tests, standalone runner at the bottom of the file).

---

## 7. Definition of Done (DoD)

- [ ] All 20 Completeness Criteria verified
- [ ] `test_add_stripe_checkout.py` passes all 20 tests (pytest and standalone runner)
- [ ] Tool returns `status="success"` on a fresh fixture
- [ ] Second run returns `status="no_op"` with zero file touches
- [ ] `dry_run=True` is byte-clean against the fixture
- [ ] Every generated `.py` parses under `ast.parse`
- [ ] Every generated function ≤ 50 LOC
- [ ] `upgrade()` in the Alembic migration ≤ 10 LOC (QS-13)
- [ ] Stripe SDK is imported lazily inside `get_stripe()` (QS-4)
- [ ] `app/main.py` is NOT touched (CC-16)
- [ ] `PaymentPublic` class body contains no PII fields (CC-17)
- [ ] Webhook handler calls `stripe.Webhook.construct_event` BEFORE any DB work (QS-1)
- [ ] `CheckConstraint` on `status` column is present (QS-8)
- [ ] `stripe>=11.0.0` appended to `requirements.txt` (CC-18)
- [ ] `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET` documented in `.env.example`
- [ ] Alembic `downgrade()` drops all 5 indexes and the table in reverse order
- [ ] `execution_time_ms > 0` in the returned `ToolResult`

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-PAY-01 | **Webhook signature MUST be verified via `stripe.Webhook.construct_event` BEFORE any DB work** | `stripe_webhook` route reads `await request.body()` (raw bytes), calls `construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)` inside a `try/except`, and raises HTTP 400 on failure BEFORE `_handle_stripe_event` or `session.commit()` run | CC-14 (webhook present) + manual review of route body |
| INV-PAY-02 | **`PaymentPublic` MUST omit `stripe_customer_id`, `stripe_session_id`, `customer_email`, and `metadata_json`** | The schema template hard-codes the PII-safe field set; `test_pii_safe_schema` slices the class body and asserts forbidden names are absent | CC-17 |
| INV-PAY-03 | **Every lifecycle transition MUST be idempotent on re-delivery** | `mark_payment_succeeded` / `mark_payment_failed` / `mark_payment_refunded` short-circuit when `payment.status` already matches the target; keyed on Stripe session id | CC-13 (≥ 5 helpers) + manual review |
| INV-PAY-04 | **`app.main` MUST import cleanly without `stripe` installed** | Stripe SDK import is lazy inside `get_stripe()`; `app/main.py` is never patched by this tool | CC-11, CC-16 |
| INV-PAY-05 | **Every generated function in `app/` MUST fit in ≤ 50 LOC** | `_max_function_loc` AST walk runs post-generation and fails the build on any violation | CC-07 |
| INV-PAY-06 | **Migration `upgrade()` MUST be ≤ 50 LOC** (refactored to ≤ 10 via `_payment_columns()` + `_create_payment_indexes()`) | The migration template hard-codes the 5-line body delegating to the two helpers | CC-07 (applies to migration too) |
| INV-PAY-07 | **Payment status MUST be one of `pending / succeeded / failed / refunded / cancelled`** | `CheckConstraint("status IN (...)")` at the DB level; `PaymentStatus` enum in Pydantic; matching server_default `"pending"` on the column | QS-8 |
| INV-PAY-08 | **Second run MUST NOT touch any file** | Pre-flight check on `get_stripe` fingerprint in `stripe_client.py`; returns `no_op` immediately | CC-02 |
| INV-PAY-09 | **Stripe secret key MUST NEVER appear in logs, exception messages, or response bodies** | Checkout and webhook exception handlers log generic strings only (`"stripe checkout session create failed"`, `"stripe webhook signature verification failed"`); HTTPException details are constant strings | QS-17 |
| INV-PAY-10 | **Webhook uses raw request bytes for signature verification** | `await request.body()` (bytes), NEVER `await request.json()` (which decodes and re-encodes) | Manual review of route body + CC-14 |

---

## 9. User Stories

### 9.1 Core Checkout Flow (US-01 .. US-05)

**US-01: Create a Stripe Checkout Session for a one-off purchase**
- **As a** SaaS customer
- **I want** to pay for a credit pack via Stripe's hosted checkout
- **So that** my card number never touches the merchant's servers
- **Given:** The tool has been applied and `STRIPE_SECRET_KEY` is set
- **When:** `POST /payments/checkout {"amount_cents": 4999, "currency": "USD", "product_name": "Starter Pack"}`
- **Then:**
  - Returns 201 with `{session_id, checkout_url, payment_id}` (CC-14)
  - A row is inserted in `payments` with `status="pending"` (CC-12)
  - The `checkout_url` can be opened in a browser and completes against the Stripe test card `4242 4242 4242 4242`

**US-02: Poll the payment record after redirect**
- **As a** frontend developer
- **I want** to refresh the status after the success redirect
- **So that** I can show "Payment complete" without trusting the redirect alone
- **Given:** `GET /payments/{payment_id}` endpoint is mounted
- **When:** The client polls every 2 s after the success redirect
- **Then:** Response transitions from `"pending"` to `"succeeded"` once the webhook lands (INV-PAY-03)

**US-03: List my past payments with pagination**
- **As a** user
- **I want** to see my purchase history
- **So that** I can download receipts
- **Given:** `GET /payments/me?skip=0&limit=50`
- **When:** I call the endpoint with a valid bearer token
- **Then:** Returns `PaymentListResponse(data=[PaymentPublic...], count=N)` — and none of the rows leak PII (INV-PAY-02, CC-17)

**US-04: Receive a signed webhook from Stripe**
- **As a** backend service
- **I want** to be the only thing that transitions payments to `succeeded`
- **So that** a client cannot spoof success by hitting `success_url` directly
- **Given:** `POST /payments/webhook/stripe` is configured in the Stripe dashboard
- **When:** Stripe delivers `checkout.session.completed` with a valid `Stripe-Signature`
- **Then:** `construct_event` verifies the signature; `mark_payment_succeeded` is called; the row transitions atomically (INV-PAY-01, INV-PAY-03)

**US-05: Reject a forged webhook**
- **As a** security reviewer
- **I want** the webhook to reject any request without a valid signature
- **So that** an attacker cannot mint payments
- **Given:** An attacker posts a fake `checkout.session.completed` to the endpoint
- **When:** `Stripe-Signature` is missing or HMAC-invalid
- **Then:** `construct_event` raises; the route returns 400 BEFORE any DB write (INV-PAY-01)

### 9.2 Webhook Reliability (US-06 .. US-10)

**US-06: Handle Stripe retry storms**
- **Given:** Stripe delivers `checkout.session.completed` three times due to a transient 5xx
- **When:** Each delivery has a valid signature
- **Then:** The first delivery transitions `pending → succeeded`; the second and third are no-ops at the CRUD layer (INV-PAY-03)

**US-07: Handle async payment success**
- **Given:** A Klarna or SEPA session completes asynchronously
- **When:** `checkout.session.async_payment_succeeded` is delivered
- **Then:** Same handler path as `checkout.session.completed` — the row transitions to `succeeded`

**US-08: Handle async payment failure**
- **Given:** An async payment declines after checkout
- **When:** `checkout.session.async_payment_failed` is delivered
- **Then:** `mark_payment_failed` writes `status="failed"` and stores the decline reason (truncated to 500 chars) in `metadata_json["failure_reason"]`

**US-09: Handle refunds**
- **Given:** Support issues a full refund via the Stripe dashboard
- **When:** `charge.refunded` is delivered with `metadata[session_id]` set
- **Then:** `mark_payment_refunded` transitions the row to `refunded` (idempotent on re-delivery)

**US-10: Silently ack unknown event types**
- **Given:** Stripe introduces a new event type we do not yet handle
- **When:** The event is delivered
- **Then:** Signature verifies; `_handle_stripe_event` matches no branch; the route returns 200 so Stripe stops retrying (QS-10)

### 9.3 Security & PII (US-11 .. US-15)

**US-11: Never leak customer email in list responses**
- **Given:** A logged-in user lists their payments
- **When:** The response serialises through `PaymentPublic`
- **Then:** No `customer_email` field is present — enforced at runtime by CC-17 slicing the class body

**US-12: Never leak the Stripe customer id**
- **Given:** `stripe_customer_id` is stored on the `Payment` row for support use
- **When:** The row is returned via `GET /payments/{id}`
- **Then:** The field is stripped at the schema boundary (INV-PAY-02)

**US-13: Never leak the secret key in logs**
- **Given:** A Stripe SDK call fails
- **When:** The route's `except Exception` fires
- **Then:** The log line is the constant string `"stripe checkout session create failed"` — no key, no payload, no stack trace echoed back to the client (INV-PAY-09)

**US-14: Reject cross-user access**
- **Given:** Two users, A and B
- **When:** User B calls `GET /payments/{payment_id}` for A's row
- **Then:** `_owner_guard` raises HTTP 404 (not 403 — we do not confirm existence) unless the caller is a superuser

**US-15: Tenant isolation when tenants table exists**
- **Given:** `app/models/tenant.py` is present at generation time
- **When:** The tool runs
- **Then:** The `Payment` model gets a `tenant_id` FK to `tenants.id` with `ondelete="SET NULL"` and an index — otherwise it is a plain nullable UUID column

### 9.4 Boot Robustness (US-16 .. US-20)

**US-16: Boot without Stripe installed**
- **Given:** A CI job that runs `python -c "import app.main"` without having installed `stripe`
- **When:** The import runs
- **Then:** Succeeds — `get_stripe()` is never called at import time, and `app.main` never imports `stripe` (CC-16, INV-PAY-04)

**US-17: Test-scaffold generates without Stripe**
- **Given:** The test harness (`test_add_stripe_checkout.py`) runs in an environment without `stripe` installed
- **When:** The tool is invoked on a fixture project
- **Then:** Generation succeeds; every `.py` parses (CC-06); the only Stripe touchpoints are module-level text strings

**US-18: Rotate the Stripe key without restart**
- **Given:** A running process with a stale `STRIPE_SECRET_KEY`
- **When:** Settings reload pulls a new key and the next `get_stripe()` call fires
- **Then:** The new key is assigned on that call — no restart required (`stripe.api_key = settings.STRIPE_SECRET_KEY` runs per-call)

**US-19: Pin the Stripe API version**
- **Given:** Stripe rolls a breaking change in the default API version
- **When:** The tool-generated app calls `get_stripe()`
- **Then:** `stripe.api_version = settings.STRIPE_API_VERSION` pins it to `"2024-06-20"` (or whatever the tool run captured) — the app is unaffected

**US-20: Idempotent tool re-run**
- **Given:** A project that already has Stripe Checkout installed
- **When:** An operator re-runs `add_stripe_checkout` by mistake
- **Then:** Returns `status="no_op"` with a note `"get_stripe already present in app/core/stripe_client.py"` and touches zero files (CC-02, INV-PAY-08)

---

## 10. Test Plan

### 10.1 Tool execution (Category A)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Success status | Fresh fixture project | `add_stripe_checkout(ToolInput(project_dir=...))` | `result.status == "success"` |
| T-02 | Idempotent second run | Fixture + first run | Call tool again | `r2.status == "no_op"`; `r2.files_created == []`; `r2.files_modified == []` |
| T-03 | Dry-run is byte-clean | Fresh fixture | `add_stripe_checkout(ToolInput(..., dry_run=True))` | `result.status == "success"`; no files created; no files modified; pre/post `.py` snapshot identical |
| T-04 | ≥ 5 files created | Fresh fixture | Run tool | `len(result.files_created) >= 5` AND each path exists |
| T-05 | ≥ 2 files modified | Fresh fixture | Run tool | `len(result.files_modified) >= 2` AND each path exists |

### 10.2 Generated code quality (Category B)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | All `.py` AST-parse | Fresh fixture + run | `ast.parse` every `*.py` under `project_dir` | All parse cleanly |
| T-07 | No function over 50 LOC | Fresh fixture + run | Walk every `FunctionDef` under `app/` | Max LOC ≤ 50 |
| T-08 | Config fields patched inside Settings class | Fresh fixture + run | Read `app/core/config.py` | All 6 `STRIPE_*` fields present; first match begins with 4-space indent |
| T-09 | Models init registers Payment | Fresh fixture + run | Read `app/models/__init__.py` | `"Payment"` present |
| T-10 | Routes init registers payments router | Fresh fixture + run | Read `app/routes/__init__.py` (if exists) | `"payment"` present (case-insensitive) |

### 10.3 Domain-specific (Category C)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | Stripe client lazy import | Fresh fixture + run | Read `app/core/stripe_client.py` | File exists; `"get_stripe"` present; `"import stripe"` present (inside function body per QS-4) |
| T-12 | Payment model class exists | Fresh fixture + run | Read `app/models/payment.py` | `"class Payment"` present |
| T-13 | Payment CRUD has ≥ 5 async helpers | Fresh fixture + run | Read `app/crud/payment.py` | `content.count("async def ") >= 5` |
| T-14 | Webhook route present | Fresh fixture + run | Read `app/api/routes/payments.py` | `"webhook"` and `"stripe"` both present (case-insensitive) |
| T-15 | 6 Stripe config fields | Fresh fixture + run | Read `app/core/config.py` | All 6 `STRIPE_*` field names present |
| T-16 | `main.py` does NOT import stripe | Fresh fixture + run | Read `app/main.py` | `"import stripe"` absent; `"stripe_client"` absent |
| T-17 | `PaymentPublic` is PII-safe | Fresh fixture + run | Slice class body out of `app/schemas/payment.py` | `"stripe_customer_id"` absent; `"customer_email"` absent |
| T-18 | `requirements.txt` includes stripe | Fresh fixture + run | Read `requirements.txt` | `"stripe>="` present |
| T-19 | Execution time recorded | Fresh fixture + run | Inspect `ToolResult.execution_time_ms` | `> 0` |
| T-20 | Project still parses after two runs | Fresh fixture + two runs | AST walk every `.py` | All parse cleanly |

### 10.4 Security review checklist (manual)

These checks are not in the automated suite but MUST be verified during any
security review of the generated code:

| # | Check | Where to look |
|---|-------|---------------|
| SR-01 | Webhook reads `await request.body()` not `request.json()` | `stripe_webhook` route body |
| SR-02 | `construct_event` is called BEFORE any DB work | `stripe_webhook` route body |
| SR-03 | Webhook signature failure returns HTTP 400 (not 500) | `stripe_webhook` except handler |
| SR-04 | Exception logs do not echo payload or headers | `create_checkout_session` and `stripe_webhook` logging |
| SR-05 | `PaymentPublic` field set matches INV-PAY-02 | `app/schemas/payment.py` |
| SR-06 | `status` CHECK constraint is present in migration | `_payment_columns()` in migration |
| SR-07 | `amount_cents` is bounded `> 0` and `<= 99_999_999` | `CheckoutSessionCreate.amount_cents` |
| SR-08 | Tenant FK uses `ondelete="SET NULL"` (not `CASCADE`) | `_PAYMENT_TENANT_COL_TENANTED` template |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `fastapi_generate_project` | Yes — must run BEFORE | Prerequisite | Provides base model, models init, config settings, routes init, alembic versions dir, requirements.txt |
| `add_multi_tenancy` | Yes — run BEFORE | Compatible | If `app/models/tenant.py` exists, the `Payment` model gets a `tenant_id` FK with `ondelete="SET NULL"` and index. Running Stripe first then tenancy requires a follow-up migration. |
| `add_webhook_receiver` | No | Compatible | Different webhook (generic HMAC) — lives on its own router prefix and does not conflict with `/payments/webhook/stripe` |
| `add_api_key_auth` | No | Compatible | API keys may call `POST /payments/checkout` as their own identity — `user_id` is stored on the row |
| `add_rbac` | Yes — run AFTER | Compatible | RBAC can further restrict `/payments/me` and `/payments/{id}`; `_owner_guard` already enforces the basic owner check |
| `add_audit_log` | Yes — run AFTER | Compatible | Audit log can hook the CRUD transitions to record every status change |
| `add_soft_delete` | No | ⚠️ Caveat | Soft-deleting a `Payment` would break webhook reconciliation; do not enable for the `payments` table |
| `add_cursor_pagination` | No | Compatible | `GET /payments/me` already accepts `skip` / `limit`; upgrading to cursor pagination is a separate concern |
| `add_search` | No | ⚠️ Caveat | Full-text search over payments must exclude `stripe_customer_id`, `customer_email`, and `metadata_json` to preserve INV-PAY-02 |
| `add_data_export` | No | ⚠️ Caveat | Exports MUST use the `PaymentPublic` schema — never the ORM row — to avoid leaking PII |
| `add_cache_layer` | No | ⚠️ Caveat | Cache must exclude `POST /payments/checkout` and `POST /payments/webhook/stripe`; webhooks MUST hit the origin every time |
| Rate-limit middleware (slowapi / generic ASGI) | No | ⚠️ Caveat | Webhook endpoint MUST be exempt from global rate limits, or attackers can amplify Stripe retries into a DoS on your app. SKILL-001 does not ship a dedicated rate-limit tool. |
| `add_webhook_receiver` (TOOL-016) | No | ✅ Compatible | The Stripe webhook route bypasses the generic receiver's signature scheme (Stripe uses its own HMAC); both can coexist on the same app. |
| `add_outbox_pattern` | No | Compatible | Payment status transitions can emit outbox events for downstream consumers |
| `add_oauth2_provider` | No | Compatible | OAuth2 tokens work for `/payments/*` if scopes are configured; webhook remains signature-verified |

**Conflicts:** `add_soft_delete` applied to the `payments` table.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py \
  requirements.txt \
  .env.example

rm -f \
  app/core/stripe_client.py \
  app/models/payment.py \
  app/schemas/payment.py \
  app/crud/payment.py \
  app/api/routes/payments.py \
  alembic/versions/add_stripe_checkout.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # runs the generated downgrade():
                       #   drop ix_payments_user_created
                       #   drop ix_payments_status_created
                       #   drop ix_payments_user_id
                       #   drop ix_payments_stripe_payment_intent_id
                       #   drop ix_payments_stripe_session_id
                       #   drop table payments
```

⚠️ **Warning:** `alembic downgrade -1` deletes the entire `payments` audit
trail. If there are live payments, run section 12.3 FIRST.

### 12.3 Data preservation rollback

If the rollback happens after real payments landed:

```bash
# 1. Snapshot the payments table to a dated archive schema.
psql "$DATABASE_URL" <<SQL
CREATE SCHEMA IF NOT EXISTS archive_$(date +%Y%m%d);
CREATE TABLE archive_$(date +%Y%m%d).payments AS TABLE payments;
SQL

# 2. Export to CSV for offline storage.
psql "$DATABASE_URL" -c "\\copy payments TO 'payments_$(date +%Y%m%d).csv' CSV HEADER"

# 3. Only then run section 12.2.
alembic downgrade -1
```

### 12.4 Stripe-side rollback

- **Dashboard webhooks**: disable the `/payments/webhook/stripe` endpoint in
  the Stripe dashboard to stop future retries.
- **In-flight sessions**: Checkout Sessions live for 24 h by default; revoke
  them by expiring programmatically (`stripe.checkout.Session.expire`) or
  let them age out.
- **Key rotation**: if rolling back because of a suspected key leak, rotate
  `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` in the dashboard BEFORE
  touching any code.

### 12.5 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

---

## 13. Edge Cases

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| EC-01 | **Webhook replay — same event delivered twice** | Signature verifies both times; first delivery transitions `pending → succeeded`; second delivery is a CRUD-layer no-op because `payment.status == "succeeded"` already (INV-PAY-03) |
| EC-02 | **Webhook signature mismatch** | `construct_event` raises; route returns HTTP 400 BEFORE any DB write; log line is `"stripe webhook signature verification failed"` with no payload echo (INV-PAY-01) |
| EC-03 | **Webhook missing `Stripe-Signature` header** | `sig_header == ""`; `construct_event` raises; HTTP 400 |
| EC-04 | **Webhook delivered after 5 minutes (replay window expired)** | `construct_event` raises `SignatureVerificationError("Timestamp outside the tolerance zone")`; HTTP 400 |
| EC-05 | **Charge refunded without `metadata[session_id]`** | `_handle_stripe_event` finds no linked session id; the event is silently acked with HTTP 200; operator must reconcile manually |
| EC-06 | **Client hits `success_url` without webhook having landed yet** | Application reads `Payment.status == "pending"`; UI shows a spinner and polls `GET /payments/{id}` until the webhook transitions the row |
| EC-07 | **User abandons checkout** | No webhook is delivered; `Payment` row stays in `pending` indefinitely; a background job may sweep `pending` rows older than 24 h to `cancelled` (not generated by this tool) |
| EC-08 | **Stripe API call fails at checkout creation** | `create_checkout_session` catches the SDK exception, logs `"stripe checkout session create failed"` (no payload), raises HTTP 502 |
| EC-09 | **Database crashes between Stripe session create and CRUD flush** | The Stripe session exists but no `Payment` row does; on retry the client gets a new session and a new row — the orphaned Stripe session ages out after 24 h |
| EC-10 | **`stripe` package not installed at boot** | `app.main` imports cleanly (lazy import); first call to `get_stripe()` raises `ModuleNotFoundError`; operator must `pip install -r requirements.txt` (INV-PAY-04) |
| EC-11 | **Idempotency key reuse at the HTTP layer** | Not enforced at the HTTP layer by this tool. CRUD-level idempotency in `mark_payment_succeeded` / `mark_payment_failed` / `mark_payment_refunded` is keyed on Stripe session id and short-circuits on re-delivery (INV-PAY-03). To add HTTP-layer idempotency keys, implement an ASGI middleware that stores `Idempotency-Key` header → response in Redis. |
| EC-12 | **Full refund via `charge.refunded`** | `mark_payment_refunded` transitions the row to `refunded`; irreversible on re-delivery |
| EC-13 | **Partial refund** | `charge.refunded` still fires but the handler does not record partial amounts (not in scope for v1); operator must reconcile via Stripe dashboard |
| EC-14 | **Cross-user access attempt** | `_owner_guard` raises HTTP 404 (deliberately, not 403 — we do not confirm existence to non-owners) |
| EC-15 | **Superuser fetches another user's payment** | `_owner_guard` short-circuits on `is_superuser`; returns the row |
| EC-16 | **Race condition: two workers handle the same event** | First writer wins via the idempotent CRUD transition; second writer flushes zero rows and returns `None` or the already-transitioned row |
| EC-17 | **Tool re-run on already-installed project** | Pre-flight detects `get_stripe` in `stripe_client.py`; returns `status="no_op"` with a clear note; touches zero files (CC-02) |
| EC-18 | **`app/models/tenant.py` created AFTER Stripe install** | Tool does not retroactively add the tenant FK; operator must write a manual migration or re-run after forcing the `no_op` off |
| EC-19 | **`amount_cents <= 0` or `> 99_999_999`** | `CheckoutSessionCreate` rejects at the Pydantic layer with HTTP 422; no Stripe call is made |
| EC-20 | **Currency code in lowercase** | Request validation requires `^[A-Z]{3}$`; lowercase rejected at HTTP 422; the CRUD layer also uppercases defensively before writing |
| EC-21 | **`metadata_json` with > 50 keys** | Pydantic rejects at the HTTP layer (HTTP 422); matches Stripe's own Metadata limit |
| EC-22 | **Webhook body exceeds 64 KiB** | FastAPI's default body-size limit rejects before the route runs; operator must increase the limit if Stripe changes its event format |
| EC-23 | **Stripe session id collision (should never happen)** | `stripe_session_id` column is `UNIQUE`; the second insert raises `IntegrityError`; CRUD flush rolls back |

---

## 14. Acceptance Criteria (Final Sign-off)

- [ ] All 20 Completeness Criteria verified via automated checks
- [ ] `test_add_stripe_checkout.py` passes all 20 tests (both pytest and standalone runner)
- [ ] Tool execution completes in < 3 s on the reference fixture
- [ ] Second run is a true no-op (status `no_op`, zero file touches)
- [ ] Dry-run snapshot equals the baseline byte-for-byte
- [ ] Every generated `.py` parses under `ast.parse`
- [ ] No function in generated `app/` exceeds 50 LOC (migration included)
- [ ] Migration `upgrade()` delegates to `_payment_columns()` + `_create_payment_indexes()` (QS-13)
- [ ] `get_stripe()` imports `stripe` lazily — `app.main` boots without the package (INV-PAY-04)
- [ ] `app/main.py` does not import `stripe` or reference `stripe_client` (CC-16)
- [ ] `PaymentPublic` class body contains none of `stripe_customer_id`, `stripe_session_id`, `customer_email`, `metadata_json` (INV-PAY-02, CC-17)
- [ ] Webhook handler calls `stripe.Webhook.construct_event` BEFORE any DB work (INV-PAY-01)
- [ ] Webhook reads `await request.body()` (raw bytes), not `request.json()` (INV-PAY-10)
- [ ] Webhook signature failure returns HTTP 400 with a sanitised log line (INV-PAY-09)
- [ ] All 6 `STRIPE_*` settings are inside the `Settings` class body with 4-space indent (CC-08)
- [ ] `stripe>=11.0.0` is present in `requirements.txt` (CC-18)
- [ ] `.env.example` documents `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_WEBHOOK_SECRET`
- [ ] Alembic `downgrade()` drops all 5 indexes and the table in reverse order
- [ ] CRUD idempotency verified by manual re-delivery of a webhook against a running instance
- [ ] Operator successfully opens a Stripe test checkout, pays with `4242 4242 4242 4242`, and observes `Payment.status` transition from `pending` to `succeeded` via the webhook path

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight
- [ ] Validate `project_dir` via `validate_project_dir`
- [ ] Invoke `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)`
- [ ] Capture any `scaffolded` files returned by the prereq layer
- [ ] Check `app/core/stripe_client.py` for the `get_stripe` fingerprint; return `no_op` if present
- [ ] Detect tenant awareness via `(app_dir / "models" / "tenant.py").exists()`
- [ ] Short-circuit to dry-run output if `inp.dry_run`

### 15.2 Stripe SDK wrapper
- [ ] Create `app/core/stripe_client.py` from `_STRIPE_CLIENT_TEMPLATE`
- [ ] Verify lazy `import stripe` sits INSIDE `get_stripe()`
- [ ] Verify `settings.STRIPE_SECRET_KEY` and `settings.STRIPE_API_VERSION` are assigned per call
- [ ] AST-parse the generated file

### 15.3 Payment SQLAlchemy model
- [ ] Create `app/models/payment.py` from `_PAYMENT_MODEL_TEMPLATE`
- [ ] Replace `TENANT_PLACEHOLDER` with `_PAYMENT_TENANT_COL_TENANTED` or `_PAYMENT_TENANT_COL_PLAIN`
- [ ] Verify `CheckConstraint("status IN ('pending','succeeded','failed','refunded','cancelled')")`
- [ ] Verify composite indexes `ix_payments_status_created`, `ix_payments_user_created`
- [ ] Append `from app.models.payment import Payment  # noqa: F401` to `app/models/__init__.py` (idempotent)
- [ ] AST-parse the generated file

### 15.4 Pydantic schemas
- [ ] Create `app/schemas/payment.py` from `_PAYMENT_SCHEMAS_TEMPLATE`
- [ ] Verify `PaymentStatus` enum (5 values)
- [ ] Verify `CheckoutSessionCreate` with `amount_cents > 0`, `currency ^[A-Z]{3}$`, `quantity 1..999`, `metadata_json max_length=50`
- [ ] Verify `PaymentPublic` omits `stripe_customer_id`, `stripe_session_id`, `customer_email`, `metadata_json` (INV-PAY-02)
- [ ] AST-parse the generated file

### 15.5 CRUD helpers
- [ ] Create `app/crud/payment.py` from `_PAYMENT_CRUD_TEMPLATE`
- [ ] Verify the 5 helpers: `create_pending_payment`, `mark_payment_succeeded`, `mark_payment_failed`, `mark_payment_refunded`, `get_payment_by_session_id`, `get_payment_by_id`, `list_user_payments`
- [ ] Verify every `mark_*` helper short-circuits on `payment.status == <target>` (INV-PAY-03)
- [ ] AST-parse the generated file

### 15.6 HTTP routes
- [ ] Create `app/api/routes/payments.py` from `_PAYMENTS_ROUTES_TEMPLATE`
- [ ] Verify helper extraction: `_build_line_items`, `_resolve_urls`, `_owner_guard`, `_handle_stripe_event` all ≤ 50 LOC
- [ ] Verify `create_checkout_session` raises HTTP 502 on SDK failure (no payload echo)
- [ ] Verify `stripe_webhook` reads `await request.body()` (raw bytes)
- [ ] Verify `construct_event` runs BEFORE `_handle_stripe_event` and BEFORE `session.commit()`
- [ ] Verify `_handle_stripe_event` handles 4 event types + silent ack of unknown types
- [ ] AST-parse the generated file

### 15.7 Alembic migration
- [ ] Resolve down-revision via `find_migration_head(versions_dir) or "0001_initial"`
- [ ] Create `alembic/versions/add_stripe_checkout.py` from `_PAYMENT_MIGRATION_TEMPLATE`
- [ ] Replace `DOWN_REV` and `TENANT_PLACEHOLDER`
- [ ] Verify `upgrade()` is ≤ 10 LOC (delegates to `_payment_columns` + `_create_payment_indexes`)
- [ ] Verify `downgrade()` drops all 5 indexes + table in reverse order
- [ ] AST-parse the generated file

### 15.8 Config patch
- [ ] Patch `app/core/config.py` with the Stripe settings block
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` if present
- [ ] Fallback anchor on `settings = Settings()`
- [ ] Final fallback: append to EOF
- [ ] Verify all 6 `STRIPE_*` fields are inside the `Settings` class body with 4-space indent (CC-08)

### 15.9 Routes init patch
- [ ] Patch `app/routes/__init__.py` with `from app.api.routes.payments import router as payments_router` + `api_router.include_router(payments_router)`
- [ ] Idempotent: no-op if import line already present

### 15.10 Requirements patch
- [ ] Append `stripe>=11.0.0` to `requirements.txt` (idempotent)
- [ ] Verify `stripe>=` present (CC-18)

### 15.11 `.env.example` patch
- [ ] Append Stripe env block with placeholder values (`sk_test_...`, `pk_test_...`, `whsec_...`)
- [ ] Idempotent: no-op if `STRIPE_SECRET_KEY` already present

### 15.12 Post-generation validation
- [ ] AST-parse every path in `files_created` with `.py` suffix
- [ ] Walk every function in `app/` and assert LOC ≤ 50 (QS-12)
- [ ] Verify `app/main.py` has NOT been modified (CC-16)

### 15.13 Return value
- [ ] Return `ToolResult` with `status="success"`, populated `files_created`, `files_modified`, `notes`, `next_steps`, and `execution_time_ms > 0`
- [ ] Notes cover: lazy SDK, PII-safe schema, webhook signature verification, migration tenant awareness
- [ ] Next steps include `pip install -r requirements.txt`, `alembic upgrade head`, env var setup, `stripe listen`, and a Stripe test card instruction

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/core/stripe_client.py",
    "app/models/payment.py",
    "app/schemas/payment.py",
    "app/crud/payment.py",
    "app/api/routes/payments.py",
    "alembic/versions/add_stripe_checkout.py"
  ],
  "files_modified": [
    "app/core/config.py",
    "app/models/__init__.py",
    "app/routes/__init__.py",
    "requirements.txt",
    ".env.example"
  ],
  "notes": [
    "Stripe Checkout added: lazy SDK wrapper, Payment model + schemas + CRUD,",
    "POST /payments/checkout, GET /payments/{id}, GET /payments/me, and",
    "POST /payments/webhook/stripe (signature-verified via stripe.Webhook.construct_event).",
    "Alembic migration for `payments` table (tenant-aware when app/models/tenant.py exists).",
    "Stripe api_version pinned to 2024-06-20.",
    "Stripe SDK is imported lazily inside get_stripe() — the app boots cleanly without `stripe` installed (the tool still adds it to requirements.txt)."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_WEBHOOK_SECRET in .env.",
    "Expose the webhook endpoint: `stripe listen --forward-to http://localhost:8000/api/v1/payments/webhook/stripe` (dev) or configure an endpoint in the Stripe dashboard (prod).",
    "Restart the FastAPI app so the /payments/* routes are loaded.",
    "Test: POST /payments/checkout with a test amount/currency; open the returned checkout_url; complete with a Stripe test card (4242 4242 4242 4242)."
  ],
  "warnings": [
    "The webhook endpoint MUST be reachable from Stripe's IP ranges in production — ensure your reverse proxy does not block it.",
    "Rotate STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET whenever a team member with production access leaves.",
    "Partial refunds are NOT tracked as a distinct status in v1 — reconcile via the Stripe dashboard if you need partial-refund reporting."
  ],
  "metrics": {
    "execution_time_ms": 1240,
    "files_created_count": 6,
    "files_modified_count": 5,
    "generated_functions_max_loc": 48,
    "migration_upgrade_loc": 5,
    "stripe_event_types_handled": 4
  }
}
```

---

*TOOL-054 spec v2 — derived from the 20 assertions in
`test_add_stripe_checkout.py` and the 1379-LOC generator at
`adapt/extend/infrastructure/add_stripe_checkout.py`.*
