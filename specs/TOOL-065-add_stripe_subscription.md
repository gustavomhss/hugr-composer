---
spec_id: "TOOL-065"
tool_name: "add_stripe_subscription"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-SUB-01"
  - "INV-SUB-02"
  - "INV-SUB-03"
  - "INV-SUB-04"
  - "INV-SUB-05"
  - "INV-SUB-06"
  - "INV-SUB-07"
  - "INV-SUB-08"
  - "INV-SUB-09"
  - "INV-SUB-10"
  - "INV-SUB-11"
  - "INV-SUB-12"
  - "INV-SUB-13"
  - "INV-SUB-14"
  - "INV-SUB-15"
completeness_criteria:
  - "CC-01"
  - "CC-02"
  - "CC-03"
  - "CC-04"
  - "CC-05"
  - "CC-06"
  - "CC-07"
  - "CC-08"
  - "CC-09"
  - "CC-10"
  - "CC-11"
  - "CC-12"
  - "CC-13"
  - "CC-14"
  - "CC-15"
  - "CC-16"
  - "CC-17"
  - "CC-18"
  - "CC-19"
  - "CC-20"
quality_standards:
  - "QS-1"
  - "QS-10"
  - "QS-11"
  - "QS-12"
  - "QS-13"
  - "QS-14"
  - "QS-15"
  - "QS-16"
  - "QS-17"
  - "QS-18"
  - "QS-19"
  - "QS-2"
  - "QS-20"
  - "QS-3"
  - "QS-4"
  - "QS-5"
  - "QS-6"
  - "QS-7"
  - "QS-8"
  - "QS-9"
test_plan:
  - "T-01"
  - "T-02"
  - "T-03"
  - "T-04"
  - "T-05"
  - "T-06"
  - "T-07"
  - "T-08"
  - "T-09"
  - "T-10"
  - "T-11"
  - "T-12"
  - "T-13"
  - "T-14"
  - "T-15"
  - "T-16"
  - "T-17"
  - "T-18"
  - "T-19"
  - "T-20"
  - "T-21"
  - "T-22"
tags:
  - "performance"
  - "payments"
  - "data"
  - "resiliency"
  - "realtime"
---
# TOOL-065: add_stripe_subscription

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_stripe_subscription` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Stripe SDK, SQLAlchemy 2.0, Alembic, pydantic-settings |
| Signature | `add_stripe_subscription(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_stripe_subscription", "description": "Add production-grade Stripe subscription billing with Subscription model, webhook receiver, proration on plan change, and idempotent event processing.", "tags": ["extend", "infrastructure"], "entry": "add_stripe_subscription"}` |
| Files created (typical) | 6 — `app/core/stripe_billing.py`, `app/models/subscription.py`, `app/schemas/subscription.py`, `app/crud/subscription.py`, `app/api/routes/subscriptions.py`, `alembic/versions/add_stripe_subscription.py` |
| Files modified (typical) | 4 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_stripe_subscription` tool installs production-grade Stripe subscription billing into a FastAPI project without requiring a developer to hand-wire the Stripe SDK, design a safe state machine, or figure out how to avoid exposing PII through list endpoints. The naive approach — calling `stripe.Subscription.create` from a request handler and trusting the HTTP redirect to confirm payment — fails in production for three reasons: client-side redirects can be replayed or tampered with, failed payment retries must be reconciled without user interaction, and plan upgrades/downgrades create proration invoices that must be computed server-side. This tool implements the correct pattern for all three cases.

The tool generates the entire subscription kit: (a) `app/core/stripe_billing.py` — a `StripeBilling` class whose methods each perform a lazy `import stripe` so the application boots cleanly on machines where the Stripe SDK is not yet installed; (b) a `Subscription` SQLAlchemy model with `stripe_subscription_id` (unique, indexed), `stripe_customer_id` (stored internally but never returned via the public schema), `plan_id`, `status` (constrained to six webhook-driven values: `active`, `trialing`, `past_due`, `canceled`, `incomplete`, `unpaid`), billing period timestamps, and `cancel_at_period_end` flag; (c) Pydantic schemas — `SubscriptionCreate` (price_id + optional trial), `SubscriptionRead` (full internal view), `SubscriptionPublic` (PII-safe, omits `stripe_customer_id`), `ChangePlanRequest`, `SubscriptionListResponse`; (d) six async CRUD helpers — `create_subscription`, `get_by_user`, `get_by_stripe_id`, `update_status`, `cancel`, `list_active`; (e) five HTTP endpoints — `POST /subscriptions` (create), `GET /subscriptions/me` (paginated), `POST /subscriptions/{id}/cancel` (schedule at period end), `POST /subscriptions/{id}/change-plan` (proration), and `POST /subscriptions/webhook/stripe` (signature-verified receiver); (f) an Alembic migration chained to the current head with three composite indexes; and (g) patches to `app/core/config.py` (three `STRIPE_*` settings inside `class Settings`), `app/models/__init__.py`, `app/routes/__init__.py`, and `requirements.txt`.

Key design decisions: the **webhook-first state machine** means status transitions (`active`, `past_due`, `canceled`, `trialing`) happen only via signed Stripe webhooks — the application never transitions state on the basis of a client-side redirect; **lazy Stripe import** inside `StripeBilling` methods means `app.main` boots cleanly even before `pip install stripe` runs; **signature verification before DB work** means `stripe.Webhook.construct_event` (HMAC-SHA256, 5-minute replay window) is called before any write; **proration on plan change** sends `proration_behavior="create_prorations"` so mid-cycle upgrades/downgrades are automatically billed; and **PII safety** means `SubscriptionPublic` omits `stripe_customer_id` so Stripe's internal customer identifier is never leaked to list callers. The tool is idempotent: it detects the `StripeBilling` fingerprint in `app/core/stripe_billing.py` and returns `status="no_op"` on second invocation without touching any file.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-13) |
| Files created | ≥ 6 | Billing helper, Subscription model, schemas, CRUD, routes, migration (CC-04) |
| Files modified | ≥ 3 | Config, models `__init__`, routes `__init__`, requirements — at least three must exist (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (CC-07) |
| `POST /subscriptions` latency | < 500 ms | Two Stripe API calls (customer + subscription create) plus one DB write |
| `GET /subscriptions/me` latency | < 30 ms | Single paginated DB query backed by `ix_subscriptions_user_status` index |
| Webhook endpoint latency | < 50 ms | HMAC verify (CPU-only) + single CRUD update |
| `stripe.Webhook.construct_event` replay window | 5 minutes | Built into Stripe SDK default tolerance |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 3 indexes |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no Stripe billing
│   ├── core/
│   │   └── config.py        # Settings class, no STRIPE_* fields
│   ├── models/
│   │   ├── __init__.py      # Base + User imports only
│   │   └── base.py
│   ├── routes/
│   │   └── __init__.py      # api_router, no subscriptions router
│   └── api/
│       └── deps.py          # CurrentUser dependency
├── alembic/versions/
│   └── 0001_initial.py
└── requirements.txt         # no stripe
```

Subscription lifecycle is unmanaged. A payment succeeds in Stripe's dashboard but the application has no record. Failed payment retries silently churn. Plan changes are implemented as cancel-and-recreate, losing proration credits.

### 4.2 Stripe billing helper (lazy import): AFTER

```python
# app/core/stripe_billing.py
"""Stripe billing helper — lazy SDK import so the app boots without `stripe` installed."""
from __future__ import annotations
import logging
from typing import Any
from app.core.config import settings

logger = logging.getLogger(__name__)


class StripeBilling:
    """Thin wrapper around the Stripe SDK for subscription operations."""

    def _get_stripe(self) -> Any:
        import stripe  # local import — keeps app.main importable without stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        return stripe

    def create_customer(self, email: str, metadata: dict[str, str] | None = None) -> Any:
        stripe = self._get_stripe()
        return stripe.Customer.create(email=email, metadata=metadata or {})

    def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        trial_period_days: int | None = None,
    ) -> Any:
        stripe = self._get_stripe()
        params: dict[str, Any] = {
            "customer": customer_id,
            "items": [{"price": price_id}],
        }
        if trial_period_days:
            params["trial_period_days"] = trial_period_days
        return stripe.Subscription.create(**params)

    def cancel_subscription(self, stripe_subscription_id: str) -> Any:
        stripe = self._get_stripe()
        return stripe.Subscription.modify(
            stripe_subscription_id, cancel_at_period_end=True
        )

    def change_plan(self, stripe_subscription_id: str, new_price_id: str) -> Any:
        stripe = self._get_stripe()
        sub = stripe.Subscription.retrieve(stripe_subscription_id)
        item_id = sub["items"]["data"][0]["id"]
        return stripe.Subscription.modify(
            stripe_subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="create_prorations",
        )

    def construct_webhook_event(self, payload: bytes, sig_header: str) -> Any:
        stripe = self._get_stripe()
        return stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )


def get_stripe_billing() -> StripeBilling:
    return StripeBilling()
```

### 4.3 Subscription model: AFTER

```python
# app/models/subscription.py
"""SQLAlchemy model for Stripe subscription records."""
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
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
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','trialing','past_due','canceled','incomplete','unpaid')",
            name="ck_subscriptions_status",
        ),
        Index("ix_subscriptions_user_status", "user_id", "status"),
        Index("ix_subscriptions_status_period_end", "status", "current_period_end"),
    )
```

### 4.4 Schemas (PII-safe public view): AFTER

```python
# app/schemas/subscription.py
class SubscriptionPublic(BaseModel):
    """PII-safe public view of a subscription record.

    ``stripe_customer_id`` is intentionally omitted.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: str
    status: SubscriptionStatus
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    created_at: datetime
```

### 4.5 Webhook handler (signature first): AFTER

```python
# app/api/routes/subscriptions.py  (webhook endpoint)
@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    session: SessionDep,
) -> dict[str, bool]:
    """Receive and verify a Stripe webhook, then dispatch the event."""
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
```

### 4.6 Config patch (settings inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Stripe subscriptions — added by add_stripe_subscription tool ---
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_BILLING_PORTAL_RETURN_URL: str = "http://localhost:8000/billing"
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land inside the `Settings` class body (4-space indent) so pydantic-settings picks them up from environment variables.

### 4.7 Typical caller usage (after install)

```python
# From any authenticated route:
from app.core.stripe_billing import get_stripe_billing

billing = get_stripe_billing()
customer = billing.create_customer(email=user.email)
sub = billing.create_subscription(
    customer_id=customer["id"],
    price_id="price_xxx",
    trial_period_days=14,
)
# Then persist via CRUD and poll status via webhook
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | `add_stripe_subscription` pre-flight checks `"StripeBilling" in app/core/stripe_billing.py` and returns `status="no_op"` with empty `files_created`/`files_modified` |
| QS-2 | **`dry_run=True` writes zero files** | Early return guarded by `if inp.dry_run:` before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | Final loop runs `ast.parse` on each created `.py` file; tool returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `stripe_billing.py`, CRUD, and routes kept small by construction; asserted by AST walk in test harness |
| QS-5 | **Stripe SDK never imported at module top level** | All `import stripe` statements live inside method bodies in `stripe_billing.py` |
| QS-6 | **Signature verification BEFORE DB write** | `construct_webhook_event` is called before `_handle_subscription_event` in the webhook handler |
| QS-7 | **Proration enabled on plan change** | `change_plan` passes `proration_behavior="create_prorations"` to `stripe.Subscription.modify` |
| QS-8 | **`SubscriptionPublic` omits `stripe_customer_id`** | Schema class verified by AST walk in `test_pii_safe_schema` |
| QS-9 | **`STRIPE_*` settings live inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-10 | **Alembic migration is chained to current head** | `_write_subscription_migration` calls `find_migration_head(versions_dir) or "0001_initial"` |
| QS-11 | **Subscription model is registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.subscription import Subscription  # noqa: F401` idempotently |
| QS-12 | **`stripe>=11.0.0` added to requirements** | `_patch_requirements` appends only if `"stripe"` absent |
| QS-13 | **Prerequisites validated before write** | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` runs first |
| QS-14 | **All HTTP endpoints require authentication** | `POST /subscriptions`, `GET /subscriptions/me`, `POST /subscriptions/{id}/cancel`, `POST /subscriptions/{id}/change-plan` all declare `current_user: CurrentUser`; webhook is secured via Stripe-Signature |
| QS-15 | **Ownership guard prevents cross-user access** | `_owner_guard(sub, current_user)` raises 404 if `sub.user_id != current_user.id` and user is not superuser |
| QS-16 | **CRUD status transitions are idempotent** | `update_status` and `cancel` check existing state before overwriting; safe to replay on webhook retry |
| QS-17 | **Tool records execution time** | `ToolResult.execution_time_ms` is computed via `_elapsed_ms(start)` on every return path |
| QS-18 | **Next steps mention `alembic` and Stripe env vars** | `next_steps` list includes `"alembic upgrade head"` and `"Set STRIPE_SECRET_KEY ..."` |
| QS-19 | **Second run keeps the project parseable** | No-op path does not corrupt any file; all `.py` remain AST-valid after two invocations |
| QS-20 | **`_handle_subscription_event` is idempotent** | Each branch calls `update_status` or `cancel` which are themselves idempotent by `stripe_subscription_id` key |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_stripe_subscription.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 6 new files | `len(result.files_created) >= 6` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 3 existing files | `len(result.files_modified) >= 3` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_BILLING_PORTAL_RETURN_URL` exist inside `class Settings` body with 4-space indent | String scan + indent check | T-08 (`test_config_fields_patched`) |
| CC-09 | `Subscription` is registered in `app/models/__init__.py` | `"Subscription" in content` of `models/__init__.py` | T-09 (`test_models_init_patched`) |
| CC-10 | Subscriptions router is registered in `app/routes/__init__.py` when that file exists | `"subscription" in content.lower()` of `routes/__init__.py` | T-10 (`test_routes_registered`) |
| CC-11 | Domain-specific files exist with correct content | Multiple sub-assertions per domain file (see section 10.3) | T-11..T-16, T-17 |
| CC-12 | `requirements.txt` contains `stripe>=` pin | `"stripe>=" in content` of `requirements.txt` | T-17 (`test_requirements_stripe`) |
| CC-13 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-18 (`test_execution_time_recorded`) |
| CC-14 | `next_steps` is non-empty and mentions `alembic` | Lowercased join of `next_steps` contains `"alembic"` | T-19 (`test_next_steps_present`) |
| CC-15 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` files after two runs | T-20 (`test_idempotent_project_still_parses`) |
| CC-16 | `app/core/stripe_billing.py` exists with `StripeBilling` class and `get_stripe_billing` factory | File exists + substring checks | T-11 (`test_stripe_billing_created`) |
| CC-17 | `stripe` is NOT imported at module top level in `stripe_billing.py` | AST walk of module-level nodes checking for `import stripe` or `from stripe` | T-21 (`test_stripe_not_top_level_import_in_billing`) |
| CC-18 | Webhook handler calls `construct_webhook_event` before `_handle_subscription_event` | `content.find("construct_webhook_event") < content.find("_handle_subscription_event")` within webhook function | T-22 (`test_webhook_signature_verified_before_db`) |
| CC-19 | `app/models/subscription.py` has all 7 required fields | Substring checks for `stripe_subscription_id`, `stripe_customer_id`, `plan_id`, `status`, `current_period_start`, `current_period_end`, `cancel_at_period_end` | T-12 (`test_subscription_model_created`) |
| CC-20 | `app/api/routes/subscriptions.py` contains `cancel` and `change-plan` endpoints | `"cancel"` and `"change-plan"` in content (case-insensitive) | T-15 (`test_cancel_and_change_plan_routes`) |

---

## 7. Definition of Done (DoD)

- [ ] All 22 tests in `test_add_stripe_subscription.py` pass
- [ ] `add_stripe_subscription.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_stripe_subscription.py` detects `"StripeBilling"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `StripeBilling._get_stripe()` imports `stripe` lazily — no module-level `import stripe` in `stripe_billing.py`
- [ ] `stripe.Webhook.construct_event` is called before any DB write in the webhook handler
- [ ] `SubscriptionPublic` does NOT declare `stripe_customer_id` as an annotated field
- [ ] `change_plan` passes `proration_behavior="create_prorations"` to Stripe
- [ ] `STRIPE_*` fields are inside `class Settings` with 4-space indent
- [ ] `_patch_models_init` idempotently appends `Subscription` import
- [ ] `_patch_requirements` adds `stripe>=11.0.0` when absent
- [ ] `find_migration_head` is used to chain the migration to the current head
- [ ] All five HTTP endpoints are authenticated (four via `CurrentUser`, one via Stripe-Signature)
- [ ] `_owner_guard` raises 404 (not 403) for cross-user access
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-SUB-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"StripeBilling" in billing_file.read_text()` short-circuits to `status="no_op"` | T-02, T-20 |
| INV-SUB-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-SUB-03 | Every generated `.py` file MUST parse as valid Python | Final loop `for path in files_created: if .py: ast.parse(p.read_text())` | T-06, T-20 |
| INV-SUB-04 | `stripe` MUST be imported lazily inside `StripeBilling` methods | No `import stripe` or `from stripe` at module top level in `stripe_billing.py` | T-21 |
| INV-SUB-05 | Signature verification MUST occur before any DB write | `construct_webhook_event` position precedes `_handle_subscription_event` in webhook handler | T-22 |
| INV-SUB-06 | `SubscriptionPublic` MUST NOT expose `stripe_customer_id` | AST walk of `SubscriptionPublic` class body; no `AnnAssign` named `stripe_customer_id` | T-16 |
| INV-SUB-07 | `STRIPE_*` settings MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-SUB-08 | `Subscription` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends import idempotently | T-09 |
| INV-SUB-09 | All user-facing endpoints MUST require `CurrentUser` authentication | `CurrentUser` parameter declared on all four non-webhook endpoints | T-10 |
| INV-SUB-10 | Plan change MUST use `proration_behavior="create_prorations"` | Hard-coded in `StripeBilling.change_plan` | T-11 |
| INV-SUB-11 | Alembic migration MUST chain to the current head | `find_migration_head(versions_dir) or "0001_initial"` | T-05 |
| INV-SUB-12 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on all return branches | T-18 |
| INV-SUB-13 | `next_steps` MUST reference `alembic` so operators know the post-install steps | Hard-coded string in the success branch | T-19 |
| INV-SUB-14 | `stripe>=11.0.0` MUST be added to `requirements.txt` | `_patch_requirements` appends when `"stripe"` absent | T-17 |
| INV-SUB-15 | Status machine MUST only transition via webhook events | `update_status` and `cancel` keyed on `stripe_subscription_id`; REST cancel only sets `cancel_at_period_end=True` | T-14, T-15 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install Stripe subscriptions into a clean FastAPI project**
- **As a** backend engineer adding recurring billing
- **I want** to run one tool call and get the full subscription kit
- **So that** I stop hand-rolling Stripe glue
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_stripe_subscription(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-SUB-01)
  - `files_created` contains ≥ 6 paths (CC-04)
  - `files_modified` contains ≥ 3 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/core/stripe_billing.py` already contains `StripeBilling`
- **When:** `add_stripe_subscription(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-SUB-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-SUB-03)
  - Verified by T-02, T-20

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **So that** I can audit before committing
- **Given:** Fresh FastAPI fixture project
- **When:** `add_stripe_subscription(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-SUB-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **So that** I can read and approve it
- **Given:** Tool just emitted `stripe_billing.py`, `crud/subscription.py`, routes
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `STRIPE_SECRET_KEY=sk_live_...` in `.env` to take effect
- **So that** I do not rebuild images for key rotation
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `STRIPE_SECRET_KEY` inside `class Settings` picks up env var (INV-SUB-07)
  - Verified by T-08

### 9.2 Webhook state machine (US-06 .. US-10)

**US-06: Receive a subscription.updated webhook**
- **As a** Stripe webhook endpoint
- **I want** to verify the signature before touching the DB
- **So that** replayed or tampered requests are rejected
- **Given:** Incoming POST to `/subscriptions/webhook/stripe` with `Stripe-Signature` header
- **When:** Webhook fires
- **Then:**
  - `billing.construct_webhook_event(payload, sig_header)` runs first (INV-SUB-05)
  - Bad signature → HTTP 400 "invalid stripe signature"
  - Valid event → `_handle_subscription_event` updates the row
  - Verified by T-22

**US-07: Status transitions only via webhooks**
- **As a** fraud-resistant billing system
- **I want** status changes to originate from signed Stripe events only
- **So that** a replay of the payment redirect cannot mark a subscription active
- **Given:** `_handle_subscription_event` dispatches on `event_type`
- **When:** `customer.subscription.updated` arrives with `status="active"`
- **Then:**
  - `update_status(session, stripe_subscription_id=..., status="active", ...)` is called
  - No endpoint accepts a `status` field in its request body
  - Verified by T-14 (model review), T-22

**US-08: Cancel at period end**
- **As a** user
- **I want** `POST /subscriptions/{id}/cancel` to schedule cancellation at period end
- **So that** I keep access until I have paid for
- **Given:** An active subscription owned by the user
- **When:** `POST /subscriptions/{id}/cancel`
- **Then:**
  - `billing.cancel_subscription(stripe_subscription_id)` sets `cancel_at_period_end=True` in Stripe
  - `update_status(..., cancel_at_period_end=True)` updates the local row
  - Returns `SubscriptionPublic` with `cancel_at_period_end=True`
  - Verified by T-15

**US-09: Change plan with proration**
- **As a** user upgrading from Starter to Pro mid-cycle
- **I want** the pro-rated charge to appear on my next invoice automatically
- **So that** I am not charged twice
- **Given:** An active subscription owned by the user
- **When:** `POST /subscriptions/{id}/change-plan` with `new_price_id`
- **Then:**
  - `billing.change_plan(stripe_subscription_id, new_price_id)` passes `proration_behavior="create_prorations"` (INV-SUB-10, QS-7)
  - Local `plan_id` updated to `new_price_id`
  - Verified by T-15

**US-10: Cross-user access denied**
- **As a** security reviewer
- **I want** `_owner_guard` to return 404 (not 403) for cross-user cancel/change-plan
- **So that** existence of a subscription is not inferrable by probing
- **Given:** User A's subscription id posted by user B
- **When:** `POST /subscriptions/{sub_a_id}/cancel` by user B
- **Then:**
  - `_owner_guard(sub, current_user)` raises `HTTPException(404, "subscription not found")`
  - No Stripe API call is made
  - Verified by route code review (INV-SUB-09)

### 9.3 PII safety (US-11 .. US-15)

**US-11: List subscriptions without leaking Stripe customer id**
- **As a** frontend developer rendering a billing page
- **I want** `GET /subscriptions/me` to return plan and status info
- **So that** I can build the UI without exposing Stripe internals to the browser
- **Given:** `SubscriptionPublic` schema
- **When:** Response is serialised
- **Then:**
  - `stripe_customer_id` is absent from every element in `data` (INV-SUB-06)
  - `plan_id`, `status`, `cancel_at_period_end`, `current_period_end` are present
  - Verified by T-16

**US-12: Internal admin view includes stripe_customer_id**
- **As a** backend service doing Stripe API lookups
- **I want** `SubscriptionRead` to include `stripe_customer_id`
- **So that** I can look up the customer without a DB join
- **Given:** `SubscriptionRead` schema
- **When:** Internal code serialises a row
- **Then:**
  - `stripe_customer_id` is present in `SubscriptionRead`
  - `SubscriptionRead` is never used as a response_model on public endpoints
  - Verified by schema inspection

**US-13: Unauthenticated access denied**
- **As a** security reviewer
- **I want** no anonymous subscription state probing
- **So that** subscription ids are not an information leak
- **Given:** All four non-webhook endpoints declare `current_user: CurrentUser`
- **When:** Anonymous request hits `/subscriptions/me`
- **Then:**
  - FastAPI DI resolves `CurrentUser`; missing auth → 401
  - Verified by route signature (INV-SUB-09)

**US-14: No stripe import at app.main boot time**
- **As a** container health-checker
- **I want** `app.main` to import without `stripe` installed
- **So that** the API container does not require the Stripe SDK
- **Given:** `StripeBilling._get_stripe()` does `import stripe` lazily
- **When:** `python -c "import app.main"` on a machine without `stripe`
- **Then:**
  - No `ImportError` raised (INV-SUB-04)
  - Verified by T-21

**US-15: requirements.txt gets the new dep**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `stripe>=11.0.0` to appear
- **So that** the billing module can import
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `stripe>=11.0.0` (idempotent: only appended if absent)
  - Verified by T-17 (INV-SUB-14)

### 9.4 Migration and CRUD (US-16 .. US-20)

**US-16: Run alembic upgrade head after install**
- **As an** ops engineer
- **I want** `alembic upgrade head` to create the `subscriptions` table cleanly
- **So that** the app does not fail on first subscription create
- **Given:** Migration chained to current head
- **When:** `alembic upgrade head`
- **Then:**
  - `subscriptions` table created with all columns
  - Three composite indexes created
  - `downgrade()` drops table and indexes
  - Verified by T-05, T-06

**US-17: Paginated subscription listing**
- **As a** UI rendering a billing history page
- **I want** `GET /subscriptions/me?skip=0&limit=20`
- **So that** users with many subscriptions do not wait for full table scan
- **Given:** `ix_subscriptions_user_status` index exists
- **When:** `get_by_user(session, user_id=..., limit=20, offset=0)` runs
- **Then:**
  - Returns `(rows, total_count)` — total count for `count` envelope field
  - Query uses `ORDER BY created_at DESC LIMIT n`
  - Verified by T-13 (CRUD test)

**US-18: CRUD cancel is idempotent**
- **As a** webhook handler receiving a duplicate `subscription.deleted` event
- **I want** `cancel(session, stripe_subscription_id=...)` to be safe to call twice
- **So that** Stripe's at-least-once delivery does not create inconsistencies
- **Given:** A subscription already in `canceled` status
- **When:** `cancel(...)` called again
- **Then:**
  - `update_status(..., status="canceled")` writes the same value idempotently
  - No error raised
  - Verified by CRUD implementation review (QS-20)

**US-19: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include migration + Stripe env var guidance
- **So that** I do not forget to expose the webhook endpoint
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"alembic upgrade head"` and env var guidance (INV-SUB-13)
  - Mentions `stripe listen --forward-to` for dev setup
  - Verified by T-19

**US-20: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **So that** the build does not blow the budget
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-SUB-12)
  - Verified by T-18

---

## 10. Test Plan

All 22 tests live in `adapt/extend/infrastructure/test_add_stripe_subscription.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `sub_t01` | `add_stripe_subscription(ToolInput(project_dir))` | `result.status == "success"` (INV-SUB-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `sub_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-SUB-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `sub_t03`; snapshot all `.py` | `add_stripe_subscription(ToolInput(dry_run=True))` | `status == "success"`; empty lists; filesystem byte-identical (INV-SUB-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `sub_t04` | Run tool | `len(files_created) >= 6`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `sub_t05` | Run tool | `len(files_modified) >= 3`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `sub_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-SUB-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `sub_t07`; run tool | AST walk `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `sub_t08`; run tool | Read `app/core/config.py` | Contains all 3 `STRIPE_*` fields; `STRIPE_SECRET_KEY` line starts with 4-space indent (INV-SUB-07, CC-08) |
| T-09 | `test_models_init_patched` | Fixture `sub_t09`; run tool | Read `app/models/__init__.py` | Contains `"Subscription"` (INV-SUB-08, CC-09) |
| T-10 | `test_routes_registered` | Fixture `sub_t10`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"subscription"` (case-insensitive) (CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-17)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_stripe_billing_created` | Fixture `sub_t11`; run tool | Read `app/core/stripe_billing.py` | File exists; contains `StripeBilling`, `get_stripe_billing`, `import stripe` (CC-16) |
| T-12 | `test_subscription_model_created` | Fixture `sub_t12`; run tool | Read `app/models/subscription.py` | Contains `class Subscription` + all 7 required fields (CC-19) |
| T-13 | `test_subscription_crud_created` | Fixture `sub_t13`; run tool | Read `app/crud/subscription.py` | File exists; `async def` count >= 5 |
| T-14 | `test_webhook_route_present` | Fixture `sub_t14`; run tool | Read `app/api/routes/subscriptions.py` | `"webhook"` and `"stripe"` present (case-insensitive) |
| T-15 | `test_cancel_and_change_plan_routes` | Fixture `sub_t15`; run tool | Read `app/api/routes/subscriptions.py` | `"cancel"` and `"change-plan"` present (CC-20) |
| T-16 | `test_pii_safe_schema` | Fixture `sub_t16`; run tool | AST-parse `app/schemas/subscription.py`; walk `SubscriptionPublic` body | No `AnnAssign` named `stripe_customer_id` (INV-SUB-06, CC-11) |
| T-17 | `test_requirements_stripe` | Fixture `sub_t17`; run tool | Read `requirements.txt` | Contains `"stripe>="` (INV-SUB-14, CC-12) |

### 10.4 Category D — Meta (T-18 .. T-22)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-18 | `test_execution_time_recorded` | Fixture `sub_t18`; run tool | Read `result.execution_time_ms` | `> 0` (INV-SUB-12, CC-13) |
| T-19 | `test_next_steps_present` | Fixture `sub_t19`; run tool | Lowercase-join `result.next_steps` | Non-empty; contains `"alembic"` (INV-SUB-13, CC-14) |
| T-20 | `test_idempotent_project_still_parses` | Fixture `sub_t20`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-SUB-01, INV-SUB-03, CC-15) |
| T-21 | `test_stripe_not_top_level_import_in_billing` | Fixture `sub_t21`; run tool | AST walk of `stripe_billing.py` module-level nodes | No `ast.Import` with `stripe`, no `ast.ImportFrom` with `module=="stripe"` (INV-SUB-04, CC-17) |
| T-22 | `test_webhook_signature_verified_before_db` | Fixture `sub_t22`; run tool | Read `app/api/routes/subscriptions.py`; find positions | `content.find("construct_webhook_event") < content.find("_handle_subscription_event")` within webhook function (INV-SUB-05, CC-18) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_stripe_subscription.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_stripe_subscription.py
```

Target: 22/22 passed, 0 failed. The standalone runner prints `TOOL-065 add_stripe_subscription: 22 passed, 0 failed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible | Checkout Sessions and Subscriptions are distinct Stripe objects; both can coexist in the same project |
| `add_stripe_refund_flow` (TOOL-066) | No | ✅ Compatible — run after or before | Refunds reference `payments.id`; subscriptions reference `users.id`; no schema conflict. A refund on a subscription payment uses TOOL-066's `POST /refunds` endpoint independently |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Webhook handlers can enqueue heavy post-payment work (provisioning, email) via `enqueue("send_email_task", ...)` without blocking the webhook response |
| `add_temporal_workflow` (TOOL-067) | No | ✅ Compatible | Temporal workflows can be started from the subscription create endpoint to handle long-running provisioning |
| `add_multi_tenancy` (TOOL-008) | Yes | ✅ Compatible — tenancy runs BEFORE | `Subscription.user_id` FK implies per-user isolation; adding a `tenant_id` column requires a separate migration if multi-tenancy is later added |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | RBAC can add `require("billing:read")` and `require("billing:write")` guards; current version only enforces `CurrentUser` |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat — audit after | Subscription status transitions (active → canceled) are natural audit events; wrap `update_status` CRUD calls after adding the audit tool |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `Subscription` rows must NOT use soft-delete — `_handle_subscription_event` on `subscription.deleted` must hard-cancel, not soft-delete |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | Subscription status change events (trial ending, payment failed) are natural triggers for transactional emails via arq `send_email_task` |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API keys resolve to a `CurrentUser` identity; can create and cancel subscriptions with the same key |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `GET /subscriptions/me` can be cursor-paginated by `created_at DESC` using `ix_subscriptions_user_status` |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Admin panel renders `Subscription` model views; add `ModelAdmin` filtered by `status`/`plan_id` |

**Conflicts:** None. `add_stripe_subscription` is strictly additive. It never modifies a pre-existing `Subscription` model if one exists; the idempotency guard skips all writes.

---

## 12. Rollback Procedure

### 12.1 Code rollback (before deploy)

```bash
git checkout HEAD -- \
  app/core/config.py \
  app/models/__init__.py \
  app/routes/__init__.py \
  requirements.txt

rm -f \
  app/core/stripe_billing.py \
  app/models/subscription.py \
  app/schemas/subscription.py \
  app/crud/subscription.py \
  app/api/routes/subscriptions.py \
  alembic/versions/add_stripe_subscription.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops subscriptions table + its three indexes
```

The `downgrade()` function drops `ix_subscriptions_user_status`, `ix_subscriptions_status_period_end`, the unique index on `stripe_subscription_id`, and then the `subscriptions` table.

### 12.3 Data preservation rollback

Archive subscription rows before downgrade if compliance requires it:

```sql
CREATE TABLE subscriptions_archive_<date> AS SELECT * FROM subscriptions;
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

The tool writes files one at a time; `git checkout HEAD --` on modified paths plus `rm` on newly created paths restores the project.

### 12.5 Emergency: Stripe webhook endpoint down

1. Remove the webhook endpoint from the Stripe dashboard to stop delivery attempts.
2. Comment out the `include_router(subscriptions_router)` call in `app/routes/__init__.py`.
3. Restart the FastAPI app; the API tier continues serving non-billing traffic.
4. On recovery, re-register the webhook in Stripe and revert step 2.

### 12.6 Uninstall validator

```bash
test ! -f app/core/stripe_billing.py || (echo "stripe_billing.py still present" && exit 1)
test ! -f app/models/subscription.py || (echo "Subscription model still present" && exit 1)
grep -q "STRIPE_SECRET_KEY" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing a prerequisite | `ensure_prerequisites` returns errors → tool returns `status="error"` with list of missing prereqs and hint to run `fastapi_generate_project` first |
| EC-03 | `app/core/stripe_billing.py` already contains `StripeBilling` | Early return `status="no_op"` with single note — zero file writes |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-SUB-02) |
| EC-05 | `alembic/versions/` missing | Migration file step is SKIPPED silently; other file writes proceed normally |
| EC-06 | `app/core/config.py` already contains `STRIPE_SECRET_KEY` | `_patch_config` early-returns; no duplicate block appended |
| EC-07 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | `_patch_config` falls back to inserting before `settings = Settings()`; last-resort appends at EOF |
| EC-08 | `requirements.txt` already contains `stripe` | `_patch_requirements` returns without modification |
| EC-09 | `app/models/__init__.py` already imports `Subscription` | `_patch_models_init` early-returns — no duplicate import |
| EC-10 | `app/routes/__init__.py` already contains `subscriptions_router` | `_register_router_in_routes_init` early-returns — no duplicate `include_router` call |
| EC-11 | Webhook receives unknown event type (e.g. `invoice.paid`) | `_handle_subscription_event` silently acks (falls through all branches); commit and return `{"received": True}` |
| EC-12 | `stripe.Webhook.construct_event` raises `SignatureVerificationError` | HTTP 400 "invalid stripe signature"; no DB write performed (INV-SUB-05) |
| EC-13 | Generated `subscription.py` model fails `ast.parse` | Final validation loop returns `status="error"` with syntax error details |
| EC-14 | `find_migration_head` returns `None` | Migration `down_revision` falls back to `"0001_initial"` |
| EC-15 | `app/api/routes/` directory missing | `_write_subscriptions_routes` creates the directory via `mkdir(parents=True, exist_ok=True)` |
| EC-16 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `subscription.py` |
| EC-17 | `app/crud/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` before writing `subscription.py` |
| EC-18 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-20) |
| EC-19 | Very small fixture project (no `app/routes/__init__.py`) | Tool still succeeds; `routes_init` patch step is conditional on file existence |
| EC-20 | User subscribes and immediately cancels within same request cycle | Local `cancel_at_period_end` is set; Stripe cancels at period end; no double-cancel triggered |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 22 tests in `test_add_stripe_subscription.py` pass
2. ✅ Tool execution time < 5 s measured on reference hardware
3. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-SUB-01)
4. ✅ `dry_run=True` produces zero filesystem writes (INV-SUB-02)
5. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-SUB-03)
6. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
7. ✅ `stripe` is NOT imported at module top level in `stripe_billing.py` (INV-SUB-04)
8. ✅ `construct_webhook_event` is called before `_handle_subscription_event` in the webhook handler (INV-SUB-05)
9. ✅ `SubscriptionPublic` does NOT declare `stripe_customer_id` as an annotated field (INV-SUB-06)
10. ✅ `STRIPE_*` settings live inside `class Settings` body with 4-space indentation (INV-SUB-07)
11. ✅ `change_plan` passes `proration_behavior="create_prorations"` (INV-SUB-10)
12. ✅ `next_steps` includes `alembic upgrade head` and Stripe env var guidance (INV-SUB-13)
13. ✅ Developer successfully creates a subscription, cancels it, verifies status via `GET /subscriptions/me`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` passes
- [ ] `app/core/stripe_billing.py` does NOT contain `"StripeBilling"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Stripe billing helper

- [ ] Write `app/core/stripe_billing.py` via `_write_stripe_billing`
- [ ] Class `StripeBilling` with methods: `_get_stripe`, `create_customer`, `create_subscription`, `cancel_subscription`, `change_plan`, `construct_webhook_event`
- [ ] All `import stripe` statements inside method bodies — NEVER at module top level
- [ ] `change_plan` passes `proration_behavior="create_prorations"` to `stripe.Subscription.modify`
- [ ] `get_stripe_billing()` factory function at module level

### 15.3 Subscription model

- [ ] Write `app/models/subscription.py` via `_write_subscription_model`
- [ ] Required columns: `id`, `user_id`, `stripe_subscription_id`, `stripe_customer_id`, `plan_id`, `status`, `current_period_start`, `current_period_end`, `cancel_at_period_end`, `created_at`, `updated_at`
- [ ] `CheckConstraint` on `status` enforcing six valid values
- [ ] `ix_subscriptions_user_status` composite index on `(user_id, status)`
- [ ] `ix_subscriptions_status_period_end` composite index on `(status, current_period_end)`
- [ ] `_patch_models_init` appends `from app.models.subscription import Subscription  # noqa: F401` idempotently

### 15.4 Schemas

- [ ] Write `app/schemas/subscription.py` via `_write_subscription_schemas`
- [ ] `SubscriptionStatus` enum: `active`, `trialing`, `past_due`, `canceled`, `incomplete`, `unpaid`
- [ ] `SubscriptionCreate` with `price_id` (min_length=1) and `trial_period_days` (optional, ge=1, le=365)
- [ ] `SubscriptionRead` includes `stripe_customer_id` (internal only)
- [ ] `SubscriptionPublic` omits `stripe_customer_id` — verified by AST walk in tests
- [ ] `ChangePlanRequest` with `new_price_id`
- [ ] `SubscriptionListResponse` with `data: list[SubscriptionPublic]` and `count: int`

### 15.5 CRUD

- [ ] Write `app/crud/subscription.py` via `_write_subscription_crud`
- [ ] Six async helpers: `create_subscription`, `get_by_user`, `get_by_stripe_id`, `update_status`, `cancel`, `list_active`
- [ ] `get_by_user` returns `(rows, total_count)` with `ORDER BY created_at DESC LIMIT n`
- [ ] `update_status` and `cancel` are idempotent by `stripe_subscription_id` key
- [ ] `list_active` filters `status IN ("active", "trialing")`

### 15.6 HTTP routes

- [ ] Write `app/api/routes/subscriptions.py` via `_write_subscriptions_routes`
- [ ] `APIRouter(prefix="/subscriptions", tags=["subscriptions"])`
- [ ] `POST ""` — requires `CurrentUser`; calls `get_stripe_billing()`, creates customer + subscription, persists row
- [ ] `GET "/me"` — requires `CurrentUser`; paginated with `skip`/`limit` query params
- [ ] `POST "/{subscription_id}/cancel"` — requires `CurrentUser`; `_owner_guard`; Stripe cancel + DB update
- [ ] `POST "/{subscription_id}/change-plan"` — requires `CurrentUser`; `_owner_guard`; Stripe change + DB update
- [ ] `POST "/webhook/stripe"` — unauthenticated at HTTP level; `construct_webhook_event` BEFORE DB write; HTTP 400 on bad signature
- [ ] `_handle_subscription_event` dispatches `customer.subscription.created/updated/deleted`

### 15.7 Alembic migration

- [ ] `find_migration_head(versions_dir) or "0001_initial"` resolves `down_revision`
- [ ] Create `subscriptions` table with all columns
- [ ] Three indexes: unique on `stripe_subscription_id`, composite `(user_id, status)`, composite `(status, current_period_end)`
- [ ] `downgrade()` drops indexes first, then table

### 15.8 Config patch

- [ ] Early-return if `"STRIPE_SECRET_KEY" in src`
- [ ] Block emits `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_BILLING_PORTAL_RETURN_URL`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.9 Routes init patch

- [ ] Early-return if import line already present
- [ ] Insert `from app.api.routes.subscriptions import router as subscriptions_router` after last `from app.` import
- [ ] Insert `api_router.include_router(subscriptions_router)` after last `include_router` call
- [ ] Preserve trailing newline

### 15.10 Requirements patch

- [ ] Add `stripe>=11.0.0` if `"stripe"` absent
- [ ] Preserve trailing newline

### 15.11 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `status="error"` with file path on `SyntaxError`

### 15.12 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain webhook-first state machine, lazy import, proration, PII safety
- [ ] `next_steps` contains `"alembic upgrade head"`, env var instructions, `stripe listen` dev hint, restart hint

### 15.13 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring lists all emitted files and the six design decisions
- [ ] `add_stripe_subscription` docstring documents the function signature and return type

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/core/stripe_billing.py",
    "/tmp/fixture/app/models/subscription.py",
    "/tmp/fixture/app/schemas/subscription.py",
    "/tmp/fixture/app/crud/subscription.py",
    "/tmp/fixture/app/api/routes/subscriptions.py",
    "/tmp/fixture/alembic/versions/add_stripe_subscription.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/models/__init__.py",
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "Stripe Subscriptions added: lazy billing helper, Subscription model + schemas + CRUD,",
    "POST /subscriptions, GET /subscriptions/me, POST /subscriptions/{id}/cancel,",
    "POST /subscriptions/{id}/change-plan, and",
    "POST /subscriptions/webhook/stripe (signature-verified via stripe.Webhook.construct_event).",
    "Alembic migration for `subscriptions` table.",
    "Stripe SDK imported lazily inside StripeBilling methods — app boots cleanly without `stripe` installed.",
    "Proration enabled on plan change (create_prorations)."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_BILLING_PORTAL_RETURN_URL in .env.",
    "Expose the webhook: `stripe listen --forward-to http://localhost:8000/api/v1/subscriptions/webhook/stripe` (dev) or configure an endpoint in the Stripe dashboard (prod).",
    "Restart the FastAPI app so the /subscriptions/* routes are loaded.",
    "Test: POST /subscriptions with a valid Stripe price_id and test card (4242 4242 4242 4242)."
  ],
  "execution_time_ms": 187
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "StripeBilling already present in app/core/stripe_billing.py — Stripe subscriptions already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 4
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/core/stripe_billing.py, app/models/subscription.py,",
    "         app/schemas/subscription.py, app/crud/subscription.py,",
    "         app/api/routes/subscriptions.py, and an Alembic migration.",
    "[dry_run] No files written."
  ],
  "next_steps": [
    "Re-run without dry_run=True to apply changes."
  ],
  "execution_time_ms": 2
}
```

Example `error` return (prereq failure):

```json
{
  "status": "error",
  "error": "Prerequisites not met:\n  - CONFIG_SETTINGS: app/core/config.py missing\n  - REQUIREMENTS_TXT: requirements.txt missing",
  "notes": [
    "These prerequisites cannot be auto-created.",
    "Generate a base project first:",
    "  fastapi_generate_project(output_dir='...', profile='api', models={...})"
  ],
  "execution_time_ms": 3
}
```

---
