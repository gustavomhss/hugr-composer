---
spec_id: "TOOL-066"
tool_name: "add_stripe_refund_flow"
version: "1.0.0"
status: "ratified"
invariants:
  - "INV-REF-01"
  - "INV-REF-02"
  - "INV-REF-03"
  - "INV-REF-04"
  - "INV-REF-05"
  - "INV-REF-06"
  - "INV-REF-07"
  - "INV-REF-08"
  - "INV-REF-09"
  - "INV-REF-10"
  - "INV-REF-11"
  - "INV-REF-12"
  - "INV-REF-13"
  - "INV-REF-14"
  - "INV-REF-15"
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
  - "CC-21"
  - "CC-22"
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
# TOOL-066: add_stripe_refund_flow

> **Status**: SPEC v1 (rigorous)
> **Last updated**: 2026-04-15

---

## 1. Overview

| Metric | Value |
|--------|-------|
| Tool name | `fastapi_add_stripe_refund_flow` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, Stripe SDK, SQLAlchemy 2.0, Alembic, pydantic-settings |
| Signature | `add_stripe_refund_flow(inp: ToolInput) -> ToolResult` |
| Parameters | `inp`: `ToolInput` with `project_dir` (absolute path to FastAPI project root) and `dry_run` flag |
| MCP descriptor | `{"name": "fastapi_add_stripe_refund_flow", "description": "Add a production-grade Stripe refund flow with Refund model, PII-safe schemas, async CRUD, REST routes, and a signature-verified webhook receiver.", "tags": ["extend", "infrastructure"], "entry": "add_stripe_refund_flow"}` |
| Files created (typical) | 6 — `app/models/refund.py`, `app/schemas/refund.py`, `app/crud/refund.py`, `app/core/stripe_refunds.py`, `app/api/routes/refunds.py`, `alembic/versions/add_stripe_refund_flow.py` |
| Files modified (typical) | 4 — `app/core/config.py`, `app/models/__init__.py`, `app/routes/__init__.py`, `requirements.txt` |

---

## 2. Purpose

The `fastapi_add_stripe_refund_flow` tool installs a production-grade Stripe refund flow into a FastAPI project — separate from and not modifying the existing Payment model — so that each concern has a single responsibility and the state machine remains unambiguous. The naive approach of adding a `refunded_at` column to the `payments` table introduces nullable columns, ambiguous status transitions (is a payment "refunded" if only partially refunded?), and no audit trail for who requested the refund or why Stripe rejected it. A dedicated `Refund` table solves all three problems.

The tool generates the entire refund kit: (a) `app/core/stripe_refunds.py` — a `create_refund` function with a lazy `import stripe` inside its body and an idempotency key of `f"refund-{payment_id}-{amount_cents}"` so that duplicate API calls (retries, double-clicks) are safe — Stripe returns the same `Refund` object without double-charging; (b) a `Refund` SQLAlchemy model with `payment_id` FK (CASCADE), `stripe_refund_id` (unique, indexed), `amount_cents`, `reason` (constrained to Stripe's three accepted values via a Pydantic field validator), `status` (constrained to `pending`/`succeeded`/`failed` by a `CheckConstraint`), and `requested_by` FK to `users.id` recording who triggered the refund via the API (null for programmatic webhook-originated refunds); (c) Pydantic schemas — `RefundRequest` (with `amount_cents` bounds and `reason` pattern), `RefundRead` (full internal view including `stripe_refund_id`), `RefundPublic` (PII-safe, omits `stripe_refund_id`), `RefundListResponse`; (d) seven async CRUD helpers — `create_pending_refund`, `mark_refund_stripe_id`, `mark_refund_succeeded`, `mark_refund_failed`, `get_refund_by_id`, `get_refund_by_stripe_id`, `list_refunds_for_payment`; (e) four HTTP endpoints — `POST /refunds` (issue), `GET /refunds/{id}` (fetch), `GET /refunds/payment/{payment_id}` (list), and `POST /refunds/webhook/stripe` (signed receiver); (f) an Alembic migration chained to the current head with four indexes; and (g) patches to `app/core/config.py` (three refund settings inside `class Settings`), `app/models/__init__.py`, `app/routes/__init__.py`, and `requirements.txt`.

Key design decisions: **single-responsibility** — the `Refund` table tracks Stripe Refund objects while the `Payment` table tracks Checkout Sessions; mixing them would require nullable columns and ambiguous FSM transitions. **Idempotent webhook** — `stripe.Webhook.construct_event` verifies the `Stripe-Signature` header (HMAC-SHA256, 5-minute replay protection) BEFORE any database write; a `SignatureVerificationError` returns HTTP 400 without touching the DB. **Audit trail** — `requested_by` FK records who triggered the refund via the API (`None` for webhook-originated refunds). **Auto-approve threshold** — refunds below `settings.REFUND_AUTO_APPROVE_THRESHOLD_CENTS` are issued immediately; larger refunds require superuser or an explicit override. **PII-safe public schema** — `RefundPublic` omits `stripe_refund_id` so Stripe's internal identifier is never leaked to list callers. The tool is idempotent: it detects the `class Refund` fingerprint in `app/models/refund.py` and returns `status="no_op"` on second invocation.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5 s | Must complete within CI step budget; measured via `execution_time_ms` in `ToolResult` (CC-13) |
| Files created | ≥ 5 | Refund model, schemas, CRUD, Stripe helper, routes, migration (CC-04) |
| Files modified | ≥ 2 | Config, models `__init__`, routes `__init__`, requirements — at least two must exist (CC-05) |
| Max function LOC in generated code | ≤ 50 | Each generated function stays auditable; enforced by AST walk over `app/` subtree (CC-07) |
| `POST /refunds` latency | < 200 ms | DB insert (pending) + optional Stripe API call for auto-approve |
| `GET /refunds/payment/{id}` latency | < 30 ms | Paginated query backed by `ix_refunds_payment_created` composite index |
| Webhook endpoint latency | < 50 ms | HMAC verify (CPU-only) + single CRUD update keyed on `stripe_refund_id` |
| Idempotency key collision rate | 0% | Key is `f"refund-{payment_id}-{amount_cents}"` — unique per payment+amount combination |
| Migration runtime | < 1 s | Single `CREATE TABLE` + 4 indexes |

---

## 4. Code Examples (Before / After)

### 4.1 Project state: BEFORE

```
project/
├── app/
│   ├── main.py              # FastAPI app, no refund flow
│   ├── core/
│   │   └── config.py        # Settings class, no refund settings
│   ├── models/
│   │   ├── __init__.py      # Base + User + Payment imports
│   │   └── payment.py       # Payment model
│   ├── routes/
│   │   └── __init__.py      # api_router, no refunds router
│   └── api/
│       └── deps.py          # CurrentUser dependency
├── alembic/versions/
│   └── 0001_initial.py
└── requirements.txt         # stripe already present or not
```

Refunds are either absent or hand-rolled per feature. Double-clicking "refund" in an admin panel may submit two Stripe API calls. There is no audit trail for who issued the refund. Webhook reconciliation is absent — the local row never transitions from `pending` to `succeeded`.

### 4.2 Stripe refund helper (lazy import + idempotency key): AFTER

```python
# app/core/stripe_refunds.py
"""Stripe refund helper — lazy SDK import with idempotency key."""
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
    """Issue a Stripe refund with an idempotency key.

    Imports the ``stripe`` SDK lazily so the app boots without it.
    The idempotency key prevents double-refunds on retry.
    """
    import stripe  # lazy import — keeps app.main importable without stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    idempotency_key = f"refund-{payment_id}-{amount_cents}"
    kwargs: dict[str, Any] = {"charge": charge_id, "amount": amount_cents}
    if reason:
        kwargs["reason"] = reason
    result = stripe.Refund.create(**kwargs, idempotency_key=idempotency_key)
    return dict(result)
```

### 4.3 Refund model: AFTER

```python
# app/models/refund.py
class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
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
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','succeeded','failed')",
            name="ck_refunds_status",
        ),
        Index("ix_refunds_payment_created", "payment_id", "created_at"),
    )
```

### 4.4 PII-safe public schema: AFTER

```python
# app/schemas/refund.py
class RefundPublic(BaseModel):
    """PII-safe public view of a refund — omits stripe_refund_id."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    amount_cents: int
    reason: str | None
    status: RefundStatus
    created_at: datetime
```

`RefundRead` (internal only) includes `stripe_refund_id`. `RefundPublic` never exposes it.

### 4.5 Webhook handler (signature first, lazy import): AFTER

```python
# app/api/routes/refunds.py  (webhook endpoint)
@router.post("/webhook/stripe")
async def stripe_refund_webhook(
    request: Request,
    session: SessionDep,
) -> dict[str, bool]:
    """Receive and verify a Stripe refund webhook, then dispatch the event."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    import stripe  # lazy import — keeps app.main importable without stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_REFUND_WEBHOOK_SECRET
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid stripe signature",
        ) from exc
    await _handle_refund_event(session, event)
    await session.commit()
    return {"received": True}
```

### 4.6 Auto-approve threshold guard: AFTER

```python
# app/api/routes/refunds.py
def _check_auto_approve(amount_cents: int, current_user: Any) -> None:
    """Raise 403 if amount exceeds threshold and user is not superuser."""
    threshold = settings.REFUND_AUTO_APPROVE_THRESHOLD_CENTS
    is_superuser = getattr(current_user, "is_superuser", False)
    if amount_cents > threshold and not is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="refund amount exceeds auto-approve threshold",
        )
```

### 4.7 Config patch (settings inside `class Settings`)

```python
# app/core/config.py  (diff, added by _patch_config)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # --- Stripe refunds — added by add_stripe_refund_flow tool ---
    STRIPE_REFUND_WEBHOOK_SECRET: str = ""
    REFUND_MAX_AMOUNT_CENTS: int = 100_000_00
    REFUND_AUTO_APPROVE_THRESHOLD_CENTS: int = 5_000
```

Anchoring on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` guarantees the fields land inside the `Settings` class body so pydantic-settings picks them up from environment variables.

### 4.8 Typical caller usage (after install)

```python
# In a payment handler, after recording that a payment succeeded:
from app.core.stripe_refunds import create_refund

stripe_refund = create_refund(
    charge_id="ch_abc123",
    amount_cents=2000,
    payment_id=payment_row.id,
    reason="requested_by_customer",
)
# Then persist via CRUD and reconcile status via webhook
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Tool is idempotent on second run** | Pre-flight checks `"class Refund" in app/models/refund.py` and returns `status="no_op"` |
| QS-2 | **`dry_run=True` writes zero files** | Early return guarded by `if inp.dry_run:` before any filesystem write |
| QS-3 | **Every generated `.py` file AST-parses** | Final loop runs `ast.parse` on each created `.py`; tool returns `status="error"` on `SyntaxError` |
| QS-4 | **No generated function exceeds 50 LOC** | Every helper in `stripe_refunds.py`, CRUD, and routes kept small; asserted by AST walk in test harness |
| QS-5 | **`stripe` SDK never imported at module top level** | `import stripe` lives inside `create_refund()` body and inside the webhook handler; verified by AST walk |
| QS-6 | **Idempotency key prevents double-refunds** | `idempotency_key = f"refund-{payment_id}-{amount_cents}"` passed to `stripe.Refund.create` |
| QS-7 | **Signature verification BEFORE DB write** | `stripe.Webhook.construct_event` called before `_handle_refund_event` in webhook handler |
| QS-8 | **`RefundPublic` omits `stripe_refund_id`** | Schema class verified by AST walk of `RefundPublic` class body in `test_pii_safe_schema` |
| QS-9 | **`REFUND_*` and `STRIPE_REFUND_*` settings inside `class Settings`** | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent |
| QS-10 | **Alembic migration is chained to current head** | `_write_refund_migration` calls `find_migration_head(versions_dir) or "0001_initial"` |
| QS-11 | **`Refund` model registered in `app/models/__init__.py`** | `_patch_models_init` appends `from app.models.refund import Refund  # noqa: F401` idempotently |
| QS-12 | **`stripe>=11.0.0` added to requirements** | `_patch_requirements` appends only if `"stripe"` absent |
| QS-13 | **Prerequisites validated before write** | `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` runs first |
| QS-14 | **Auto-approve threshold enforced** | `_check_auto_approve` raises HTTP 403 when `amount_cents > REFUND_AUTO_APPROVE_THRESHOLD_CENTS` and user is not superuser |
| QS-15 | **`REFUND_MAX_AMOUNT_CENTS` hard cap enforced** | Route raises HTTP 422 when `amount_cents > settings.REFUND_MAX_AMOUNT_CENTS` |
| QS-16 | **CRUD transitions are idempotent** | `mark_refund_succeeded` checks `if refund.status == "succeeded": return refund` — safe to replay webhook |
| QS-17 | **`requested_by` FK is null for webhook-originated refunds** | `create_pending_refund` accepts `requested_by: uuid.UUID | None` |
| QS-18 | **Tool records execution time** | `ToolResult.execution_time_ms` computed via `_elapsed_ms(start)` on every return path |
| QS-19 | **Next steps mention `alembic` and Stripe env vars** | `next_steps` includes `"alembic upgrade head"` and env var guidance |
| QS-20 | **Second run keeps the project parseable** | No-op path corrupts no file; all `.py` remain AST-valid after two invocations |

---

## 6. Completeness Criteria

Every criterion is tied to a real assertion in `test_add_stripe_refund_flow.py`.

| ID | Criterion | Verification | Test |
|----|-----------|--------------|------|
| CC-01 | Tool returns `status="success"` on a fresh project | `result.status == "success"` | T-01 (`test_success_status`) |
| CC-02 | Second run returns `status="no_op"` with zero file ops | `r2.status == "no_op"` and both lists empty | T-02 (`test_idempotent`) |
| CC-03 | `dry_run=True` writes zero bytes to the filesystem | `before == after` dict over every `.py` in tree | T-03 (`test_dry_run`) |
| CC-04 | Tool creates at least 5 new files | `len(result.files_created) >= 5` and each path exists | T-04 (`test_files_created_count`) |
| CC-05 | Tool modifies at least 2 existing files | `len(result.files_modified) >= 2` and each path exists | T-05 (`test_files_modified_count`) |
| CC-06 | Every generated `.py` AST-parses cleanly | `ast.parse` over all `.py` files in project tree | T-06 (`test_all_py_parse`) |
| CC-07 | No generated function exceeds 50 LOC in `app/` | AST walk of `FunctionDef`/`AsyncFunctionDef`, `max_loc <= 50` | T-07 (`test_no_function_over_50_loc`) |
| CC-08 | `STRIPE_REFUND_WEBHOOK_SECRET`, `REFUND_MAX_AMOUNT_CENTS`, `REFUND_AUTO_APPROVE_THRESHOLD_CENTS` exist inside `class Settings` body with 4-space indent | String scan + indent check on line containing `STRIPE_REFUND_WEBHOOK_SECRET` | T-08 (`test_config_fields_patched`) |
| CC-09 | `Refund` is registered in `app/models/__init__.py` | `"Refund" in content` of `models/__init__.py` | T-09 (`test_models_init_patched`) |
| CC-10 | Refunds router is registered in `app/routes/__init__.py` when that file exists | `"refund" in content.lower()` of `routes/__init__.py` | T-10 (`test_routes_registered`) |
| CC-11 | `app/models/refund.py` exists with all 7 required columns | File exists + substring checks for all column names | T-12 (`test_refund_model_has_required_columns`) |
| CC-12 | `requirements.txt` contains `stripe>=` pin | `"stripe>=" in content` of `requirements.txt` | T-17 (`test_requirements_stripe`) |
| CC-13 | `execution_time_ms` is a positive integer on the success path | `result.execution_time_ms > 0` | T-19 (`test_execution_time_recorded`) |
| CC-14 | `next_steps` is non-empty and mentions `alembic` | Lowercased join of `next_steps` contains `"alembic"` | T-20 (`test_next_steps_present`) |
| CC-15 | Running the tool twice leaves the project AST-parseable | `ast.parse` over all `.py` after two runs | T-21 (`test_idempotent_project_still_parses`) |
| CC-16 | `app/models/refund.py` exists with `class Refund` | File exists + `"class Refund" in content` | T-11 (`test_refund_model_created`) |
| CC-17 | `app/crud/refund.py` has at least 6 async CRUD helpers | `content.count("async def ") >= 6` | T-13 (`test_refund_crud_created`) |
| CC-18 | `app/core/stripe_refunds.py` exists with `create_refund` and lazy `import stripe` | File exists + `"create_refund"` + `"import stripe"` + no module-top-level `stripe` import | T-14 (`test_stripe_refunds_lazy_import`) |
| CC-19 | `app/api/routes/refunds.py` contains `/webhook/stripe` endpoint | `"webhook"` and `"stripe"` present (case-insensitive) | T-15 (`test_webhook_route_present`) |
| CC-20 | `RefundPublic` does NOT declare `stripe_refund_id` as an annotated field | AST walk of `RefundPublic` class body; no `AnnAssign` named `stripe_refund_id` | T-16 (`test_pii_safe_schema`) |
| CC-21 | `app/core/stripe_refunds.py` contains `idempotency_key` | `"idempotency_key" in content` | T-18 (`test_idempotency_key_in_refund_helper`) |
| CC-22 | `stripe` is NOT imported at module top level in `app/api/routes/refunds.py` | AST walk of module-level nodes | T-22 (`test_stripe_not_top_level_in_routes`) |

---

## 7. Definition of Done (DoD)

- [ ] All 22 tests in `test_add_stripe_refund_flow.py` pass
- [ ] `add_stripe_refund_flow.py` runs `ast.parse` on every created `.py` file before returning success
- [ ] `add_stripe_refund_flow.py` detects `"class Refund"` fingerprint and returns `status="no_op"` on second run
- [ ] `dry_run=True` returns success with empty `files_created`/`files_modified`
- [ ] `create_refund()` imports `stripe` lazily — no module-level `import stripe` in `stripe_refunds.py`
- [ ] `stripe.Webhook.construct_event` is called before any DB write in the webhook handler
- [ ] `RefundPublic` does NOT declare `stripe_refund_id` as an annotated field
- [ ] `create_refund` passes `idempotency_key=f"refund-{payment_id}-{amount_cents}"`
- [ ] `REFUND_*` fields are inside `class Settings` with 4-space indent
- [ ] `_patch_models_init` idempotently appends `Refund` import
- [ ] `_patch_requirements` adds `stripe>=11.0.0` when absent
- [ ] `find_migration_head` is used to chain the migration to the current head
- [ ] `mark_refund_succeeded` and `mark_refund_failed` are idempotent
- [ ] `_check_auto_approve` raises HTTP 403 when threshold exceeded by non-superuser
- [ ] `execution_time_ms` is set on every return path (success, no_op, dry_run, error)
- [ ] Tool exits within 5 s on a fresh fixture project
- [ ] `MCP_TOOL` descriptor exposes `{name, description, tags, entry}` quartet

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-REF-01 | The tool is ALWAYS idempotent on second invocation | Fingerprint check `"class Refund" in refund_model_file.read_text()` short-circuits to `status="no_op"` | T-02, T-21 |
| INV-REF-02 | `dry_run=True` NEVER writes to disk | Early return guarded by `if inp.dry_run:` before any write | T-03 |
| INV-REF-03 | Every generated `.py` file MUST parse as valid Python | Final loop `ast.parse(p.read_text())` for each created `.py` | T-06, T-21 |
| INV-REF-04 | `stripe` MUST be imported lazily inside `create_refund()` and the webhook handler | No module-level `import stripe` in `stripe_refunds.py`; no module-level `import stripe` in `refunds.py` routes | T-14, T-22 |
| INV-REF-05 | Idempotency key MUST be `f"refund-{payment_id}-{amount_cents}"` | Hard-coded in `create_refund` body | T-18 |
| INV-REF-06 | Signature verification MUST occur before any DB write in the webhook handler | `stripe.Webhook.construct_event` called before `_handle_refund_event` | T-15 (webhook route review) |
| INV-REF-07 | `RefundPublic` MUST NOT expose `stripe_refund_id` | AST walk of `RefundPublic` class body | T-16 |
| INV-REF-08 | `REFUND_*` settings MUST live inside `class Settings` body | `_patch_config` anchors on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30` with 4-space indent | T-08 |
| INV-REF-09 | `Refund` MUST be registered in `app/models/__init__.py` | `_patch_models_init` appends import idempotently | T-09 |
| INV-REF-10 | All user-facing endpoints MUST require `CurrentUser` | `CurrentUser` parameter declared on all three non-webhook endpoints | T-10 |
| INV-REF-11 | `mark_refund_succeeded`/`mark_refund_failed` MUST be idempotent | Early return when `refund.status` already matches target | T-13 (CRUD review) |
| INV-REF-12 | Alembic migration MUST chain to the current head | `find_migration_head(versions_dir) or "0001_initial"` | T-05 |
| INV-REF-13 | `ToolResult.execution_time_ms` MUST be positive on every return path | `_elapsed_ms(start)` called on all return branches | T-19 |
| INV-REF-14 | `next_steps` MUST reference `alembic` | Hard-coded string in the success branch | T-20 |
| INV-REF-15 | `stripe>=11.0.0` MUST be added to `requirements.txt` | `_patch_requirements` appends when `"stripe"` absent | T-17 |

---

## 9. User Stories

### 9.1 Core install flow (US-01 .. US-05)

**US-01: Install the refund flow into a clean FastAPI project**
- **As a** backend engineer adding refund capability
- **I want** to run one tool call and get the full refund kit
- **So that** I stop hand-rolling Stripe refund glue
- **Given:** A FastAPI project with `app/core/config.py`, `app/models/base.py`, `alembic/versions/`, `requirements.txt`
- **When:** `add_stripe_refund_flow(ToolInput(project_dir=...))`
- **Then:**
  - Returns `ToolResult.status == "success"` (INV-REF-01)
  - `files_created` contains ≥ 5 paths (CC-04)
  - `files_modified` contains ≥ 2 paths (CC-05)
  - Verified by T-01, T-04, T-05

**US-02: Re-run the tool on an already-installed project**
- **As a** CI job that re-runs tooling on every commit
- **I want** the tool to skip work when already applied
- **So that** I do not corrupt the project
- **Given:** Project where `app/models/refund.py` already contains `class Refund`
- **When:** `add_stripe_refund_flow(...)` invoked a second time
- **Then:**
  - Returns `status="no_op"` (INV-REF-01)
  - `files_created == []` and `files_modified == []`
  - All `.py` files still AST-parse (INV-REF-03)
  - Verified by T-02, T-21

**US-03: Dry-run to preview changes**
- **As a** developer reviewing a tool invocation
- **I want** to see what would change without touching files
- **Given:** Fresh FastAPI fixture project
- **When:** `add_stripe_refund_flow(ToolInput(project_dir=..., dry_run=True))`
- **Then:**
  - Returns `status="success"` with informational `notes`
  - `files_created == []` and `files_modified == []`
  - Filesystem byte-identical before and after (INV-REF-02)
  - Verified by T-03

**US-04: Generated project stays auditable**
- **As a** code reviewer
- **I want** every generated function to be short
- **Given:** Tool just emitted `stripe_refunds.py`, `crud/refund.py`, `routes/refunds.py`
- **When:** I AST-walk `app/` for functions
- **Then:**
  - No `FunctionDef`/`AsyncFunctionDef` has `end_lineno - lineno + 1 > 50` (QS-4)
  - Verified by T-07

**US-05: Config fields bind from environment variables**
- **As an** ops engineer
- **I want** `REFUND_AUTO_APPROVE_THRESHOLD_CENTS=10000` in `.env` to take effect
- **Given:** pydantic-settings reads `class Settings`
- **When:** `Settings()` is instantiated at boot
- **Then:**
  - `REFUND_AUTO_APPROVE_THRESHOLD_CENTS` inside `class Settings` picks up env var (INV-REF-08)
  - Verified by T-08

### 9.2 Idempotency and double-refund safety (US-06 .. US-10)

**US-06: User double-clicks the refund button**
- **As a** user who clicks "Refund" twice in quick succession
- **I want** only one refund to be issued
- **So that** I am not double-refunded by Stripe
- **Given:** `create_refund` with `idempotency_key=f"refund-{payment_id}-{amount_cents}"`
- **When:** The same `(payment_id, amount_cents)` is submitted twice
- **Then:**
  - Stripe returns the same `Refund` object on the second call (INV-REF-05)
  - No double-charge occurs
  - Verified by T-18

**US-07: Webhook retry delivers `charge.refund.updated` twice**
- **As a** Stripe retry mechanism
- **I want** the webhook handler to handle duplicate delivery gracefully
- **Given:** `mark_refund_succeeded` is idempotent
- **When:** `charge.refund.updated` with `status="succeeded"` arrives twice
- **Then:**
  - First call: transitions `pending → succeeded`
  - Second call: early return, no DB write, no error (INV-REF-11)
  - Verified by CRUD review

**US-08: Verify webhook signature before touching the DB**
- **As a** security reviewer
- **I want** the webhook handler to reject unsigned or tampered requests
- **Given:** Incoming POST to `/refunds/webhook/stripe` with `Stripe-Signature` header
- **When:** Webhook fires
- **Then:**
  - `stripe.Webhook.construct_event(payload, sig_header, STRIPE_REFUND_WEBHOOK_SECRET)` runs first (INV-REF-06)
  - Bad signature → HTTP 400 "invalid stripe signature"; no DB write
  - Valid event → `_handle_refund_event` updates the row
  - Verified by T-15

**US-09: Small refund auto-approved; large refund requires superuser**
- **As a** customer support agent (non-superuser)
- **I want** to issue a $10 refund without approval
- **But not** a $500 refund, which must go through a superuser
- **Given:** `REFUND_AUTO_APPROVE_THRESHOLD_CENTS=5000`
- **When:**
  - Agent posts `POST /refunds` with `amount_cents=1000` → HTTP 201 (below threshold)
  - Agent posts `POST /refunds` with `amount_cents=50000` → HTTP 403 (above threshold, not superuser)
  - Superuser posts with `amount_cents=50000` → HTTP 201 (superuser bypass)
- **Then:**
  - Behavior verified by `_check_auto_approve` logic (QS-14)

**US-10: No stripe import at app.main boot time**
- **As a** container health-checker
- **I want** `app.main` to import without `stripe` installed
- **Given:** `import stripe` lives inside `create_refund()` body only
- **When:** `python -c "import app.main"` on a machine without `stripe`
- **Then:**
  - No `ImportError` raised (INV-REF-04)
  - Verified by T-14, T-22

### 9.3 PII safety (US-11 .. US-15)

**US-11: List payment refunds without leaking stripe_refund_id**
- **As a** frontend developer rendering a refund history page
- **I want** `GET /refunds/payment/{payment_id}` to return refund amount and status
- **So that** the browser never sees Stripe's internal refund id
- **Given:** `RefundPublic` schema
- **When:** Response is serialised
- **Then:**
  - `stripe_refund_id` is absent from every element in `data` (INV-REF-07)
  - `amount_cents`, `status`, `reason`, `created_at` are present
  - Verified by T-16

**US-12: Internal service resolves `stripe_refund_id` for re-query**
- **As a** backend service calling Stripe's API to check refund status
- **I want** `RefundRead` to include `stripe_refund_id`
- **Given:** `RefundRead` schema
- **When:** Internal code serialises a row
- **Then:**
  - `stripe_refund_id` is present in `RefundRead`
  - `RefundRead` is never used as a `response_model` on public endpoints

**US-13: Unauthenticated access denied**
- **As a** security reviewer
- **I want** no anonymous refund state probing
- **Given:** All three non-webhook endpoints declare `current_user: CurrentUser`
- **When:** Anonymous request hits `/refunds/payment/{payment_id}`
- **Then:**
  - FastAPI DI resolves `CurrentUser`; missing auth → 401 (INV-REF-10)

**US-14: Audit trail records who issued the refund**
- **As a** compliance officer
- **I want** to know which user triggered each refund
- **Given:** `create_pending_refund(session, ..., requested_by=current_user.id)`
- **When:** Agent issues a refund via the API
- **Then:**
  - `requested_by` column holds the agent's `user_id`
  - `requested_by` is `None` for webhook-originated refunds
  - Verified by T-12 (column check)

**US-15: requirements.txt gets the new dep**
- **As a** `pip install -r requirements.txt` invocation
- **I want** `stripe>=11.0.0` to appear
- **Given:** Tool patches `requirements.txt`
- **When:** File is re-read
- **Then:**
  - Contains `stripe>=11.0.0` (idempotent: appended only if absent) (INV-REF-15)
  - Verified by T-17

### 9.4 Migration and CRUD (US-16 .. US-20)

**US-16: Run alembic upgrade head after install**
- **As an** ops engineer
- **I want** `alembic upgrade head` to create the `refunds` table cleanly
- **Given:** Migration chained to current head
- **When:** `alembic upgrade head`
- **Then:**
  - `refunds` table created with all columns + `ck_refunds_status` check constraint
  - Four indexes created
  - `downgrade()` drops indexes then table
  - Verified by T-05, T-06

**US-17: Paginated refund listing by payment**
- **As a** UI showing refund history
- **I want** `GET /refunds/payment/{payment_id}?skip=0&limit=50`
- **Given:** `ix_refunds_payment_created` composite index
- **When:** `list_refunds_for_payment(session, payment_id, limit=50, offset=0)` runs
- **Then:**
  - Returns `(rows, total_count)` ordered by `created_at DESC`
  - Verified by T-13 (CRUD count check)

**US-18: Fetch single refund**
- **As a** user checking a specific refund
- **I want** `GET /refunds/{refund_id}`
- **Given:** Refund exists and is owned by current user (or user is superuser)
- **When:** Request is made
- **Then:**
  - Returns `RefundPublic` (no `stripe_refund_id`)
  - Cross-user access raises HTTP 404 (ownership enforced)
  - Verified by T-15 (routes review)

**US-19: Operator knows the next commands to run**
- **As a** developer who just ran the tool
- **I want** `next_steps` to include migration + Stripe env var guidance
- **Given:** Success return path
- **When:** Caller inspects `result.next_steps`
- **Then:**
  - Contains `"alembic upgrade head"` and env var guidance (INV-REF-14)
  - Mentions `stripe listen --forward-to` for dev setup
  - Verified by T-20

**US-20: Execution is fast enough for CI**
- **As a** CI pipeline
- **I want** the tool to finish in seconds
- **Given:** Fresh fixture project
- **When:** Tool runs end-to-end
- **Then:**
  - `execution_time_ms > 0` and (in practice) < 5000 (INV-REF-13)
  - Verified by T-19

---

## 10. Test Plan

All 22 tests live in `adapt/extend/infrastructure/test_add_stripe_refund_flow.py` and each test creates a fresh fixture project via `create_fixture_project(name=...)`.

### 10.1 Category A — Tool execution (T-01 .. T-05)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | `test_success_status` | Fixture `refund_t01` | `add_stripe_refund_flow(ToolInput(project_dir))` | `result.status == "success"` (INV-REF-01, CC-01) |
| T-02 | `test_idempotent` | Fixture `refund_t02`; run tool once | Run tool a second time | `r2.status == "no_op"`; both lists empty (INV-REF-01, CC-02) |
| T-03 | `test_dry_run` | Fixture `refund_t03`; snapshot all `.py` | `add_stripe_refund_flow(ToolInput(dry_run=True))` | `status == "success"`; empty lists; filesystem byte-identical (INV-REF-02, CC-03) |
| T-04 | `test_files_created_count` | Fixture `refund_t04` | Run tool | `len(files_created) >= 5`; every path exists on disk (CC-04) |
| T-05 | `test_files_modified_count` | Fixture `refund_t05` | Run tool | `len(files_modified) >= 2`; every path exists on disk (CC-05) |

### 10.2 Category B — Generated code quality (T-06 .. T-10)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-06 | `test_all_py_parse` | Fixture `refund_t06`; run tool | AST-parse every `.py` in project | No `SyntaxError` (INV-REF-03, CC-06) |
| T-07 | `test_no_function_over_50_loc` | Fixture `refund_t07`; run tool | AST walk `app/` for `FunctionDef`/`AsyncFunctionDef` | `max_loc <= 50` (QS-4, CC-07) |
| T-08 | `test_config_fields_patched` | Fixture `refund_t08`; run tool | Read `app/core/config.py` | Contains all 3 refund fields; `STRIPE_REFUND_WEBHOOK_SECRET` line starts with 4-space indent (INV-REF-08, CC-08) |
| T-09 | `test_models_init_patched` | Fixture `refund_t09`; run tool | Read `app/models/__init__.py` | Contains `"Refund"` (INV-REF-09, CC-09) |
| T-10 | `test_routes_registered` | Fixture `refund_t10`; run tool | Read `app/routes/__init__.py` if it exists | Contains `"refund"` (case-insensitive) (INV-REF-10, CC-10) |

### 10.3 Category C — Domain-specific modules (T-11 .. T-18)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-11 | `test_refund_model_created` | Fixture `refund_t11`; run tool | Read `app/models/refund.py` | File exists; contains `"class Refund"` (CC-16) |
| T-12 | `test_refund_model_has_required_columns` | Fixture `refund_t12`; run tool | Read `app/models/refund.py` | Contains all 7 columns: `payment_id`, `stripe_refund_id`, `amount_cents`, `reason`, `status`, `requested_by`, `created_at` (CC-11) |
| T-13 | `test_refund_crud_created` | Fixture `refund_t13`; run tool | Read `app/crud/refund.py` | File exists; `async def` count >= 6 (CC-17) |
| T-14 | `test_stripe_refunds_lazy_import` | Fixture `refund_t14`; run tool | Read `app/core/stripe_refunds.py` + AST walk | File exists; `"create_refund"` present; `"import stripe"` present; no module-level `ast.Import` with name `"stripe"` (INV-REF-04, CC-18) |
| T-15 | `test_webhook_route_present` | Fixture `refund_t15`; run tool | Read `app/api/routes/refunds.py` | File exists; `"webhook"` and `"stripe"` present (case-insensitive) (INV-REF-06, CC-19) |
| T-16 | `test_pii_safe_schema` | Fixture `refund_t16`; run tool | AST-parse `app/schemas/refund.py`; walk `RefundPublic` body | No `AnnAssign` named `stripe_refund_id` in `RefundPublic` (INV-REF-07, CC-20) |
| T-17 | `test_requirements_stripe` | Fixture `refund_t17`; run tool | Read `requirements.txt` | Contains `"stripe>="` (INV-REF-15, CC-12) |
| T-18 | `test_idempotency_key_in_refund_helper` | Fixture `refund_t18`; run tool | Read `app/core/stripe_refunds.py` | `"idempotency_key"` present (INV-REF-05, CC-21) |

### 10.4 Category D — Meta (T-19 .. T-22)

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | `test_execution_time_recorded` | Fixture `refund_t19`; run tool | Read `result.execution_time_ms` | `> 0` (INV-REF-13, CC-13) |
| T-20 | `test_next_steps_present` | Fixture `refund_t20`; run tool | Lowercase-join `result.next_steps` | Non-empty; contains `"alembic"` (INV-REF-14, CC-14) |
| T-21 | `test_idempotent_project_still_parses` | Fixture `refund_t21`; run tool twice | AST-parse every `.py` | No `SyntaxError` (INV-REF-01, INV-REF-03, CC-15) |
| T-22 | `test_stripe_not_top_level_in_routes` | Fixture `refund_t22`; run tool | AST walk `app/api/routes/refunds.py` module-level nodes | No `ast.Import` with `stripe`, no `ast.ImportFrom` with `module=="stripe"` (INV-REF-04, CC-22) |

### 10.5 Test execution

```bash
PYTHONPATH=. pytest adapt/extend/infrastructure/test_add_stripe_refund_flow.py -v
# or standalone:
PYTHONPATH=. python3 adapt/extend/infrastructure/test_add_stripe_refund_flow.py
```

Target: 22/22 passed, 0 failed. The standalone runner prints `TOOL-066 add_stripe_refund_flow: 22 passed, 0 failed`.

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_stripe_subscription` (TOOL-065) | No | ✅ Compatible — run before or after | Subscriptions and Refunds are distinct Stripe objects and distinct tables; no schema conflict. A refund on a subscription-related payment uses TOOL-066 independently |
| `add_stripe_checkout` (TOOL-054) | No | ✅ Compatible — run after checkout | Checkout Sessions produce `payments` rows; `refunds.payment_id` FKs to `payments.id`; TOOL-054 must be installed first (or `payments` table must exist) |
| `add_arq_worker` (TOOL-053) | No | ✅ Compatible | Refund creation can be enqueued for batch processing; webhook handler can enqueue downstream jobs (fulfilment reversal, email) |
| `add_temporal_workflow` (TOOL-067) | No | ✅ Compatible | A Temporal workflow can orchestrate: issue refund → confirm via webhook → trigger fulfilment reversal |
| `add_multi_tenancy` (TOOL-008) | No | ⚠️ Caveat | `Refund` has no `tenant_id` column; multi-tenant apps should add a `tenant_id` migration manually or run TOOL-008 before TOOL-066 and extend the migration |
| `add_rbac` (TOOL-012) | Yes | ✅ Compatible — RBAC runs AFTER | RBAC can add `require("refunds:write")` to `POST /refunds`; current version only enforces `CurrentUser` + superuser check |
| `add_audit_log` (TOOL-005) | No | ⚠️ Caveat | Refund lifecycle transitions (pending → succeeded) are natural audit events; instrument `mark_refund_*` CRUD calls after adding the audit tool |
| `add_soft_delete` (TOOL-001) | No | ⚠️ Caveat | `Refund` rows MUST NOT use soft-delete — they are a financial audit trail |
| `add_email_templates` (TOOL-055) | No | ✅ Compatible | `succeeded` webhook event is a natural trigger for a "Your refund is on its way" transactional email |
| `add_cursor_pagination` (TOOL-002) | No | ✅ Compatible | `GET /refunds/payment/{id}` can be cursor-paginated by `created_at DESC` using `ix_refunds_payment_created` |
| `add_sqladmin` (TOOL-056) | No | ✅ Compatible | Admin panel renders `Refund` model views; add `ModelAdmin` filtered by `status`/`payment_id` |
| `add_api_key_auth` (TOOL-010) | No | ✅ Compatible | API keys resolve to a `CurrentUser` identity; can issue refunds and query refund history |

**Conflicts:** None. `add_stripe_refund_flow` is strictly additive. It never modifies an existing `Refund` model if one exists.

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
  app/models/refund.py \
  app/schemas/refund.py \
  app/crud/refund.py \
  app/core/stripe_refunds.py \
  app/api/routes/refunds.py \
  alembic/versions/add_stripe_refund_flow.py
```

### 12.2 Database rollback (after deploy)

```bash
alembic downgrade -1   # drops refunds table + its four indexes
```

The `downgrade()` function drops `ix_refunds_payment_created`, `ix_refunds_requested_by`, `ix_refunds_payment_id`, `ix_refunds_stripe_refund_id`, then the `refunds` table.

### 12.3 Data preservation rollback

Archive refund rows before downgrade if compliance requires it:

```sql
CREATE TABLE refunds_archive_<date> AS SELECT * FROM refunds;
```

### 12.4 Failure mode: tool partially modified files

```bash
git status --porcelain | grep '^ M' | awk '{print $2}' | xargs git checkout --
find . -name '*.tmp_*' -delete
```

### 12.5 Emergency: Stripe refund webhook endpoint down

1. Remove the webhook endpoint from the Stripe dashboard to stop delivery.
2. Comment out `include_router(refunds_router)` in `app/routes/__init__.py`.
3. Restart the FastAPI app.
4. On recovery, re-register the webhook and revert step 2.
5. Manually reconcile any `pending` refunds by querying `SELECT * FROM refunds WHERE status = 'pending'` and calling `stripe.Refund.retrieve(stripe_refund_id)` to check their status.

### 12.6 Uninstall validator

```bash
test ! -f app/models/refund.py || (echo "Refund model still present" && exit 1)
test ! -f app/core/stripe_refunds.py || (echo "stripe_refunds.py still present" && exit 1)
grep -q "STRIPE_REFUND_WEBHOOK_SECRET" app/core/config.py && echo "config still patched" && exit 1
echo "rollback verified"
```

---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-01 | Tool runs on a project with no `app/` directory | `validate_project_dir` fails → `ToolResult(status="error", error=...)` with `execution_time_ms > 0` |
| EC-02 | Tool runs on a project missing a prerequisite | `ensure_prerequisites` returns errors → `status="error"` with list + hint to run `fastapi_generate_project` first |
| EC-03 | `app/models/refund.py` already contains `class Refund` | Early return `status="no_op"` — zero file writes (INV-REF-01) |
| EC-04 | `inp.dry_run=True` | Returns `status="success"` with dry-run notes; NO file touched; `execution_time_ms` still recorded (INV-REF-02) |
| EC-05 | `alembic/versions/` missing | Migration file step is SKIPPED silently; other file writes proceed normally |
| EC-06 | `app/core/config.py` already contains `STRIPE_REFUND_WEBHOOK_SECRET` | `_patch_config` early-returns; no duplicate block appended |
| EC-07 | `app/core/config.py` lacks the `ACCESS_TOKEN_EXPIRE_MINUTES` anchor | Falls back to inserting before `settings = Settings()`; last-resort appends at EOF |
| EC-08 | `requirements.txt` already contains `stripe` | `_patch_requirements` returns without modification |
| EC-09 | `app/models/__init__.py` already imports `Refund` | `_patch_models_init` early-returns — no duplicate import |
| EC-10 | `app/routes/__init__.py` already contains `refunds_router` | `_register_router_in_routes_init` early-returns — no duplicate call |
| EC-11 | Webhook receives unknown event type (e.g. `customer.updated`) | `_handle_refund_event` silently acks; commit and return `{"received": True}` |
| EC-12 | `stripe.Webhook.construct_event` raises `SignatureVerificationError` | HTTP 400 "invalid stripe signature"; no DB write (INV-REF-06) |
| EC-13 | `amount_cents` in `RefundRequest` is 0 or negative | Pydantic `Field(gt=0)` rejects with HTTP 422 before handler executes |
| EC-14 | `amount_cents` exceeds `REFUND_MAX_AMOUNT_CENTS` | Route raises HTTP 422 "refund amount exceeds maximum" (QS-15) |
| EC-15 | `amount_cents` exceeds `REFUND_AUTO_APPROVE_THRESHOLD_CENTS` and user is not superuser | `_check_auto_approve` raises HTTP 403 "refund amount exceeds auto-approve threshold" (QS-14) |
| EC-16 | `reason` value not in `{duplicate, fraudulent, requested_by_customer}` | Pydantic `Field(pattern=...)` rejects with HTTP 422 |
| EC-17 | `find_migration_head` returns `None` | Migration `down_revision` falls back to `"0001_initial"` |
| EC-18 | `app/api/routes/` directory missing | `_write_refunds_routes` creates directory via `mkdir(parents=True, exist_ok=True)` |
| EC-19 | `app/schemas/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-20 | `app/crud/` directory missing | Created via `mkdir(parents=True, exist_ok=True)` |
| EC-21 | Tool runs twice back-to-back via CI | Second run returns `no_op`; project AST remains parseable (T-21) |
| EC-22 | `payments` table does not exist when migration runs | Alembic raises `ForeignKeyViolation`; operator must run `add_stripe_checkout` or equivalent first |

---

## 14. Acceptance Criteria (Final Sign-off)

1. ✅ All 22 tests in `test_add_stripe_refund_flow.py` pass
2. ✅ Tool execution time < 5 s measured on reference hardware
3. ✅ Second invocation returns `status="no_op"` with empty `files_created`/`files_modified` (INV-REF-01)
4. ✅ `dry_run=True` produces zero filesystem writes (INV-REF-02)
5. ✅ Every generated `.py` file AST-parses cleanly on first and second runs (INV-REF-03)
6. ✅ No generated function in `app/` exceeds 50 LOC (QS-4)
7. ✅ `stripe` is NOT imported at module top level in `stripe_refunds.py` or `refunds.py` routes (INV-REF-04)
8. ✅ `create_refund` passes `idempotency_key=f"refund-{payment_id}-{amount_cents}"` (INV-REF-05)
9. ✅ `stripe.Webhook.construct_event` called before `_handle_refund_event` in webhook handler (INV-REF-06)
10. ✅ `RefundPublic` does NOT declare `stripe_refund_id` as an annotated field (INV-REF-07)
11. ✅ `REFUND_*` settings live inside `class Settings` body with 4-space indentation (INV-REF-08)
12. ✅ `mark_refund_succeeded` and `mark_refund_failed` are idempotent (INV-REF-11)
13. ✅ `next_steps` includes `alembic upgrade head` and env var guidance (INV-REF-14)
14. ✅ Developer successfully issues a refund, verifies `GET /refunds/{id}` shows `pending`, receives webhook, verifies status transitions to `succeeded`

---

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks

- [ ] `validate_project_dir(inp.project_dir)` returns no error
- [ ] `ensure_prerequisites(BASE_MODEL, MODELS_INIT, CONFIG_SETTINGS, ROUTES_INIT, ALEMBIC_VERSIONS, REQUIREMENTS_TXT)` passes
- [ ] `app/models/refund.py` does NOT contain `"class Refund"` (otherwise → `no_op`)
- [ ] If `inp.dry_run`, emit dry-run notes and return before any write

### 15.2 Refund model

- [ ] Write `app/models/refund.py` via `_write_refund_model`
- [ ] Columns: `id`, `payment_id` (FK to `payments.id` CASCADE), `stripe_refund_id` (unique nullable), `amount_cents`, `reason`, `status` (server_default="pending"), `requested_by` (nullable FK to `users.id` SET NULL), `created_at`
- [ ] `CheckConstraint("status IN ('pending','succeeded','failed')", name="ck_refunds_status")`
- [ ] `Index("ix_refunds_payment_created", "payment_id", "created_at")`
- [ ] `_patch_models_init` appends `from app.models.refund import Refund  # noqa: F401` idempotently

### 15.3 Schemas

- [ ] Write `app/schemas/refund.py` via `_write_refund_schemas`
- [ ] `RefundStatus` enum: `pending`, `succeeded`, `failed`
- [ ] `RefundRequest` with `payment_id: uuid.UUID`, `amount_cents: int = Field(gt=0, le=99_999_999)`, `reason: str | None = Field(pattern="^(duplicate|fraudulent|requested_by_customer)$")`
- [ ] `RefundRead` includes `stripe_refund_id` (internal only)
- [ ] `RefundPublic` omits `stripe_refund_id` — verified by AST walk in tests
- [ ] `RefundListResponse` with `data: list[RefundPublic]` and `count: int`

### 15.4 CRUD

- [ ] Write `app/crud/refund.py` via `_write_refund_crud`
- [ ] Seven async helpers: `create_pending_refund`, `mark_refund_stripe_id`, `mark_refund_succeeded`, `mark_refund_failed`, `get_refund_by_id`, `get_refund_by_stripe_id`, `list_refunds_for_payment`
- [ ] `mark_refund_succeeded`: early return if `refund.status == "succeeded"` already
- [ ] `mark_refund_failed`: early return if `refund.status == "failed"` already
- [ ] `list_refunds_for_payment`: returns `(rows, total_count)` with `ORDER BY created_at DESC LIMIT n`

### 15.5 Stripe refunds helper

- [ ] Write `app/core/stripe_refunds.py` via `_write_stripe_refunds`
- [ ] `create_refund(*, charge_id, amount_cents, payment_id, reason)` function
- [ ] `import stripe` inside function body — NOT at module top level
- [ ] `idempotency_key = f"refund-{payment_id}-{amount_cents}"`
- [ ] `stripe.api_key = settings.STRIPE_SECRET_KEY` (read at call time, never logged)
- [ ] Returns `dict(result)` (plain dict, not Stripe object)

### 15.6 HTTP routes

- [ ] Write `app/api/routes/refunds.py` via `_write_refunds_routes`
- [ ] `APIRouter(prefix="/refunds", tags=["refunds"])`
- [ ] `POST ""` — requires `CurrentUser`; `_check_auto_approve`; hard cap check; `create_pending_refund`; commit
- [ ] `GET "/payment/{payment_id}"` — requires `CurrentUser`; paginated with `skip`/`limit`
- [ ] `GET "/{refund_id}"` — requires `CurrentUser`; ownership check (superuser bypass)
- [ ] `POST "/webhook/stripe"` — unauthenticated at HTTP level; `import stripe` lazily; `construct_event` BEFORE `_handle_refund_event`; HTTP 400 on bad signature
- [ ] `_handle_refund_event` dispatches `charge.refund.updated` with `status=="succeeded"/"failed"`
- [ ] `_check_auto_approve(amount_cents, current_user)` raises HTTP 403 when threshold exceeded

### 15.7 Alembic migration

- [ ] `find_migration_head(versions_dir) or "0001_initial"` resolves `down_revision`
- [ ] Create `refunds` table with all columns + `ck_refunds_status` constraint via `_refund_columns()` helper
- [ ] Four indexes: unique on `stripe_refund_id`, on `payment_id`, on `requested_by`, composite `(payment_id, created_at DESC)`
- [ ] `downgrade()` drops indexes first, then table

### 15.8 Config patch

- [ ] Early-return if `"STRIPE_REFUND_WEBHOOK_SECRET" in src`
- [ ] Block emits `STRIPE_REFUND_WEBHOOK_SECRET`, `REFUND_MAX_AMOUNT_CENTS`, `REFUND_AUTO_APPROVE_THRESHOLD_CENTS`
- [ ] 4-space indent (class body)
- [ ] Anchor on `ACCESS_TOKEN_EXPIRE_MINUTES: int = 30`
- [ ] Fallback: before `settings = Settings()` line
- [ ] Last-resort fallback: append at EOF

### 15.9 Routes init patch

- [ ] Early-return if import line already present
- [ ] Insert `from app.api.routes.refunds import router as refunds_router`
- [ ] Insert `api_router.include_router(refunds_router)`
- [ ] Preserve trailing newline

### 15.10 Requirements patch

- [ ] Add `stripe>=11.0.0` if `"stripe"` absent
- [ ] Preserve trailing newline

### 15.11 Validation

- [ ] Loop over `files_created`; for every `.py` call `ast.parse(p.read_text())`
- [ ] Return `status="error"` with file path on `SyntaxError`

### 15.12 Result assembly

- [ ] Return `ToolResult(status="success", files_created, files_modified, notes, next_steps, execution_time_ms=_elapsed_ms(start))`
- [ ] `notes` explain lazy SDK, idempotency key, PII safety, auto-approve threshold, webhook-first state machine
- [ ] `next_steps` contains `"alembic upgrade head"`, env var instructions, `stripe listen` dev hint

### 15.13 Documentation

- [ ] `MCP_TOOL` dict exposes `name`, `description`, `tags`, `entry`
- [ ] Module docstring explains single-responsibility design, idempotent webhook, audit trail, auto-approve, PII safety
- [ ] `add_stripe_refund_flow` docstring documents the function signature and return type

---

## 16. Documentation Output

Example `ToolResult` JSON (success path on a fixture project):

```json
{
  "status": "success",
  "files_created": [
    "/tmp/fixture/app/models/refund.py",
    "/tmp/fixture/app/schemas/refund.py",
    "/tmp/fixture/app/crud/refund.py",
    "/tmp/fixture/app/core/stripe_refunds.py",
    "/tmp/fixture/app/api/routes/refunds.py",
    "/tmp/fixture/alembic/versions/add_stripe_refund_flow.py"
  ],
  "files_modified": [
    "/tmp/fixture/app/models/__init__.py",
    "/tmp/fixture/app/core/config.py",
    "/tmp/fixture/app/routes/__init__.py",
    "/tmp/fixture/requirements.txt"
  ],
  "notes": [
    "Stripe Refund flow added: lazy SDK wrapper with idempotency key,",
    "Refund model + PII-safe schemas + CRUD,",
    "POST /refunds, GET /refunds/{id}, GET /refunds/payment/{payment_id},",
    "POST /refunds/webhook/stripe (signature-verified).",
    "Alembic migration for `refunds` table.",
    "Auto-approve threshold: refunds <= REFUND_AUTO_APPROVE_THRESHOLD_CENTS are issued immediately.",
    "Stripe SDK is imported lazily inside create_refund() — the app boots cleanly without `stripe` installed."
  ],
  "next_steps": [
    "pip install -r requirements.txt  # installs `stripe`",
    "alembic upgrade head",
    "Set STRIPE_REFUND_WEBHOOK_SECRET, REFUND_MAX_AMOUNT_CENTS, REFUND_AUTO_APPROVE_THRESHOLD_CENTS in .env.",
    "Expose the webhook endpoint to Stripe dashboard or use: `stripe listen --forward-to http://localhost:8000/api/v1/refunds/webhook/stripe`",
    "Test: POST /refunds with a valid payment_id and amount_cents."
  ],
  "execution_time_ms": 163
}
```

Example `no_op` return (second invocation):

```json
{
  "status": "no_op",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "class Refund already present in app/models/refund.py — Stripe Refund flow is already installed, skipped."
  ],
  "next_steps": [],
  "execution_time_ms": 3
}
```

Example `dry_run` return:

```json
{
  "status": "success",
  "files_created": [],
  "files_modified": [],
  "notes": [
    "[dry_run] Would create app/models/refund.py, app/schemas/refund.py,",
    "         app/crud/refund.py, app/api/routes/refunds.py,",
    "         app/core/stripe_refunds.py, and an Alembic migration.",
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
