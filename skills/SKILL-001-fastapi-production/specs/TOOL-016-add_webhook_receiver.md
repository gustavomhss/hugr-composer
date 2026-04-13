# TOOL-016: add_webhook_receiver

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_webhook_receiver` |
| Category | EXTEND > Real-time |
| Complexity | High |
| Dependencies | Existing project, Alembic, Redis (idempotency cache + queue), ARQ (background handler), httpx |
| Signature | `add_webhook_receiver(project_dir: str, providers: list[Literal["stripe","github","internal"]] | None = None, idempotency_ttl_seconds: int = 86400, signature_tolerance_seconds: int = 300, max_payload_bytes: int = 1_048_576) -> dict` |
| Parameters | `project_dir`: project root path<br>`providers`: list of pre-built provider verifiers to enable (None = all)<br>`idempotency_ttl_seconds`: how long event_ids stay deduped<br>`signature_tolerance_seconds`: clock skew tolerance for signed timestamps<br>`max_payload_bytes`: hard cap on incoming body size |

---

## 2. Purpose

The `fastapi_add_webhook_receiver` tool adds a generic, hardened inbound webhook endpoint so the application can accept events from third-party providers (Stripe, GitHub, Shopify, Twilio, the internal TOOL-015 webhook_sender from a sister service, or any custom partner) without every integration rebuilding signature verification, replay protection, idempotency, and handler dispatch from scratch. Inbound webhooks are the silent attack surface of most APIs — a missing timestamp check lets an attacker replay a refund event forever, a missing signature verification lets anyone hit the endpoint with a forged Stripe payload, and a missing idempotency cache lets a well-meaning retry charge a customer twice. Getting the receiver correct is more important than getting the business logic correct.

Each inbound request is validated against the provider's specific signing scheme (Stripe `v1=...`, GitHub `X-Hub-Signature-256`, custom HMAC schemes supported via a pluggable verifier registry), deduped by event id via a Redis `SET NX EX` so a duplicate delivery within the TTL window is absorbed without invoking the handler twice, persisted to a `webhook_events` audit table so customer support can inspect exactly which events arrived and when, and dispatched to a registered handler asynchronously via ARQ so the receiver returns 200 OK (or 202 Accepted) in under 100 ms regardless of how expensive the handler is. Key design decisions: handlers never run in the request path (they always enqueue) so the provider's retry timer never fires because of slow processing; replay attacks blocked via timestamp tolerance (±5 minutes by default, configurable per provider); tampering blocked via `hmac.compare_digest` constant-time comparison; duplicate deliveries absorbed by the idempotency cache with a 24-hour TTL; and a dead-letter table for events whose handler exhausts retries so operators can replay them manually after investigating.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Dev waits in CLI |
| Files modified | ≤ 4 global files | Predictability |
| Files created | ≥ 10 (verifier base + N providers, dispatcher, registry, model, crud, routes, schemas, migration, tests) | Predictability |
| Receive endpoint p99 | < 50 ms | Verify + dedupe + enqueue, no handler execution |
| Verify latency | < 5 ms | HMAC SHA-256 + constant-time compare |
| Dedupe lookup | < 1 ms | Redis SET NX |
| Background handler latency | NOT included in receive endpoint SLO | runs out-of-band |
| Migration runtime | < 5s | One new table |
| Memory overhead | < 5 MB per worker | Provider verifier instances are stateless |

---

## 4. Code Examples (Before / After)

### 4.1 Model (NEW)
```python
# app/models/webhook_inbound.py
from datetime import datetime
from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base
import uuid


class InboundWebhook(Base):
    __tablename__ = "inbound_webhooks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    provider_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(127), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    raw_headers: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="received")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id", name="uq_inbound_webhook_event"),
        CheckConstraint(
            "status IN ('received','processing','succeeded','failed','duplicate')",
            name="ck_inbound_webhooks_status",
        ),
    )
```

### 4.2 Verifier base + providers (NEW)
```python
# app/core/inbound_webhooks/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VerifiedEvent:
    provider: str
    event_id: str
    event_type: str
    payload: dict


class InboundVerifier(ABC):
    name: str

    @abstractmethod
    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        """
        Returns a VerifiedEvent on success.
        Raises HTTPException(400) on signature mismatch.
        Raises HTTPException(401) on missing headers.
        """
```

```python
# app/core/inbound_webhooks/providers/stripe.py
import hashlib
import hmac
import json
import time

from fastapi import HTTPException

from app.core.config import settings
from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent

TOLERANCE = settings.INBOUND_WEBHOOK_SIGNATURE_TOLERANCE


class StripeVerifier(InboundVerifier):
    name = "stripe"

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        sig_header = headers.get("stripe-signature")
        if not sig_header:
            raise HTTPException(401, "Missing Stripe-Signature")

        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        try:
            ts = int(parts.get("t", 0))
        except ValueError:
            raise HTTPException(400, "Invalid Stripe signature timestamp")

        if abs(int(time.time()) - ts) > TOLERANCE:
            raise HTTPException(400, "Stripe signature timestamp out of tolerance")

        signed_payload = f"{ts}.".encode("ascii") + body
        expected = hmac.new(
            settings.STRIPE_WEBHOOK_SECRET.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        actual = parts.get("v1", "")
        if not hmac.compare_digest(expected, actual):
            raise HTTPException(400, "Stripe signature mismatch")

        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON body")

        return VerifiedEvent(
            provider="stripe",
            event_id=event["id"],
            event_type=event["type"],
            payload=event,
        )
```

```python
# app/core/inbound_webhooks/providers/github.py
import hashlib
import hmac
import json

from fastapi import HTTPException

from app.core.config import settings
from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent


class GitHubVerifier(InboundVerifier):
    name = "github"

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        sig_header = headers.get("x-hub-signature-256")
        if not sig_header or not sig_header.startswith("sha256="):
            raise HTTPException(401, "Missing X-Hub-Signature-256")

        expected = hmac.new(
            settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(f"sha256={expected}", sig_header):
            raise HTTPException(400, "GitHub signature mismatch")

        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON body")

        delivery_id = headers.get("x-github-delivery")
        event_type = headers.get("x-github-event", "unknown")
        if not delivery_id:
            raise HTTPException(400, "Missing X-GitHub-Delivery header")

        return VerifiedEvent(
            provider="github",
            event_id=delivery_id,
            event_type=event_type,
            payload=event,
        )
```

```python
# app/core/inbound_webhooks/providers/internal.py
# Reuses the signer from add_webhook_sender for symmetry.
import json
from fastapi import HTTPException

from app.core.config import settings
from app.core.inbound_webhooks.base import InboundVerifier, VerifiedEvent
from app.core.webhooks.signer import verify_signature


class InternalVerifier(InboundVerifier):
    name = "internal"

    def verify(self, body: bytes, headers: dict[str, str]) -> VerifiedEvent:
        sig = headers.get("x-signature")
        if not sig:
            raise HTTPException(401, "Missing X-Signature")
        if not verify_signature(settings.INTERNAL_WEBHOOK_SECRET, body, sig):
            raise HTTPException(400, "Internal signature mismatch")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "Invalid JSON body")

        event_id = headers.get("x-event-id")
        event_type = headers.get("x-event-type", "unknown")
        if not event_id:
            raise HTTPException(400, "Missing X-Event-Id header")

        return VerifiedEvent(
            provider="internal",
            event_id=event_id,
            event_type=event_type,
            payload=payload,
        )
```

### 4.3 Registry (NEW)
```python
# app/core/inbound_webhooks/registry.py
from app.core.inbound_webhooks.base import InboundVerifier
from app.core.inbound_webhooks.providers.stripe import StripeVerifier
from app.core.inbound_webhooks.providers.github import GitHubVerifier
from app.core.inbound_webhooks.providers.internal import InternalVerifier

_VERIFIERS: dict[str, InboundVerifier] = {
    "stripe": StripeVerifier(),
    "github": GitHubVerifier(),
    "internal": InternalVerifier(),
}


def get_verifier(provider: str) -> InboundVerifier:
    if provider not in _VERIFIERS:
        from fastapi import HTTPException

        raise HTTPException(404, f"Unknown provider: {provider}")
    return _VERIFIERS[provider]


# Handler registry: provider -> event_type -> async fn
_HANDLERS: dict[tuple[str, str], list] = {}


def webhook_handler(provider: str, event_type: str):
    """
    Decorator. Register an async fn as the handler for a (provider, event_type) pair.

    Usage:
        @webhook_handler("stripe", "payment_intent.succeeded")
        async def handle_payment(event: VerifiedEvent) -> None:
            ...
    """

    def deco(fn):
        _HANDLERS.setdefault((provider, event_type), []).append(fn)
        return fn

    return deco


def get_handlers(provider: str, event_type: str) -> list:
    return _HANDLERS.get((provider, event_type), [])
```

### 4.4 Idempotency cache (NEW)
```python
# app/core/inbound_webhooks/idempotency.py
from app.core.config import settings
from app.core.redis import get_redis

TTL = settings.INBOUND_WEBHOOK_IDEMPOTENCY_TTL


async def claim_event(provider: str, event_id: str) -> bool:
    """
    SET NX with TTL — returns True if this is the first time we see this id.
    Returns False if it's a duplicate (replay).
    """
    redis = await get_redis()
    key = f"inbound:webhook:{provider}:{event_id}"
    return bool(await redis.set(key, "1", nx=True, ex=TTL))
```

### 4.5 Routes (NEW)
```python
# app/api/routes/inbound_webhooks.py
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.inbound_webhooks.idempotency import claim_event
from app.core.inbound_webhooks.registry import get_verifier
from app.core.queue import get_arq_pool
from app.crud import inbound_webhook as crud_iwh

router = APIRouter(prefix="/webhooks/incoming", tags=["webhooks-incoming"])


@router.post("/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def receive(provider: str, request: Request, session: SessionDep):
    body = await request.body()
    if len(body) > settings.INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES:
        return JSONResponse({"detail": "Payload too large"}, status_code=413)

    headers = {k.lower(): v for k, v in request.headers.items()}

    verifier = get_verifier(provider)  # 404 if unknown
    event = verifier.verify(body, headers)  # 400/401 on bad signature

    # Idempotency: first-time wins
    is_first = await claim_event(event.provider, event.event_id)
    if not is_first:
        # Persist a duplicate row for visibility but skip dispatch
        await crud_iwh.upsert_duplicate(
            session,
            provider=event.provider,
            provider_event_id=event.event_id,
            event_type=event.event_type,
        )
        return {"status": "duplicate"}

    inbound = await crud_iwh.create_received(
        session,
        provider=event.provider,
        provider_event_id=event.event_id,
        event_type=event.event_type,
        payload=event.payload,
        raw_headers=headers,
    )

    pool = await get_arq_pool()
    await pool.enqueue_job("process_inbound_webhook", str(inbound.id))

    return {"status": "accepted"}
```

### 4.6 Background dispatcher (NEW)
```python
# app/workers/inbound_webhook_worker.py
from datetime import datetime, timezone

from app.core.db import async_session_maker
from app.core.inbound_webhooks.base import VerifiedEvent
from app.core.inbound_webhooks.registry import get_handlers
from app.crud import inbound_webhook as crud_iwh


async def process_inbound_webhook(ctx: dict, inbound_id: str) -> None:
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
            for h in handlers:
                await h(event)
            inbound.status = "succeeded"
            inbound.processed_at = datetime.now(timezone.utc)
        except Exception as exc:
            inbound.status = "failed"
            inbound.error = repr(exc)[:500]
            inbound.processed_at = datetime.now(timezone.utc)
            raise  # ARQ will retry the job
        finally:
            await session.commit()
```

### 4.7 Example handler (BEFORE / AFTER)
```python
# Before: dev had no clean place to handle Stripe events
# After:
from app.core.inbound_webhooks.base import VerifiedEvent
from app.core.inbound_webhooks.registry import webhook_handler


@webhook_handler("stripe", "payment_intent.succeeded")
async def on_payment_succeeded(event: VerifiedEvent) -> None:
    payment_id = event.payload["data"]["object"]["id"]
    # ... business logic
```

### 4.8 Migration
```python
# alembic/versions/0016_add_webhook_receiver.py
from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"


def upgrade() -> None:
    op.create_table(
        "inbound_webhooks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(127), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("raw_headers", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), server_default="received", nullable=False),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_inbound_webhook_event"),
        sa.CheckConstraint(
            "status IN ('received','processing','succeeded','failed','duplicate')",
            name="ck_inbound_webhooks_status",
        ),
    )
    op.create_index("ix_inbound_webhooks_provider", "inbound_webhooks", ["provider"])
    op.create_index("ix_inbound_webhooks_received_at", "inbound_webhooks", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_inbound_webhooks_received_at", "inbound_webhooks")
    op.drop_index("ix_inbound_webhooks_provider", "inbound_webhooks")
    op.drop_table("inbound_webhooks")
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **All payloads HMAC-verified** | Per-provider verifier uses `hmac.compare_digest`; mismatch → 400. |
| QS-2 | **Replay attacks blocked** | Stripe verifier checks timestamp tolerance (5 min default). |
| QS-3 | **Duplicates absorbed** | Redis SET NX with TTL; first-time wins; later attempts → 200 with `status:duplicate`. |
| QS-4 | **Receive endpoint always responds quickly** | Handlers run in background via ARQ; receive returns 202 in < 50 ms. |
| QS-5 | **Body size cap enforced** | `len(body) > MAX_PAYLOAD_BYTES` → 413 before any verification. |
| QS-6 | **Constant-time signature compare** | `hmac.compare_digest` everywhere. |
| QS-7 | **Provider extensibility** | New verifiers added by subclassing `InboundVerifier` and registering in registry. |
| QS-8 | **Handler registry is decorator-based** | `@webhook_handler(provider, event_type)` registers async functions. |
| QS-9 | **All received events persisted** | DB row created for every accepted (or duplicate) event for audit and replay. |
| QS-10 | **Idempotency at TWO layers** | Redis cache (fast path) + DB unique constraint (durable). |
| QS-11 | **Provider secrets are mandatory** | Settings raise at startup if a configured provider's secret is missing. |
| QS-12 | **5xx from handler triggers ARQ retry** | Worker re-raises exception; ARQ retries with its own backoff. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `InboundWebhook` model exists | File `app/models/webhook_inbound.py` |
| CC-02 | `app/core/inbound_webhooks/base.py` defines `InboundVerifier` ABC + `VerifiedEvent` | File exists |
| CC-03 | A verifier per provider exists in `providers/` | grep |
| CC-04 | `app/core/inbound_webhooks/registry.py` exists with `get_verifier` + `webhook_handler` | File exists |
| CC-05 | `app/core/inbound_webhooks/idempotency.py` exists with `claim_event` | File exists |
| CC-06 | `app/api/routes/inbound_webhooks.py` exists with `/webhooks/incoming/{provider}` | File exists |
| CC-07 | `app/workers/inbound_webhook_worker.py` with `process_inbound_webhook` ARQ task | File exists |
| CC-08 | `app/crud/inbound_webhook.py` exists | File exists |
| CC-09 | `app/schemas/inbound_webhook.py` exists | File exists |
| CC-10 | Migration `0016_add_webhook_receiver.py` exists | File exists |
| CC-11 | Migration creates table + UNIQUE(provider, provider_event_id) | Inspect upgrade() |
| CC-12 | Status enum CheckConstraint | grep |
| CC-13 | Settings: `INBOUND_WEBHOOK_IDEMPOTENCY_TTL`, `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE`, `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES` | grep |
| CC-14 | Per-provider secrets settings (e.g. `STRIPE_WEBHOOK_SECRET`) | grep |
| CC-15 | Routes registered in `app/api/main.py` | grep |
| CC-16 | OpenAPI exposes the receiver endpoint | curl /openapi.json |
| CC-17 | New file `tests/test_webhook_receiver.py` with 30 tests | File exists |
| CC-18 | Existing tests pass | pytest 0 failures |
| CC-19 | All files parse | Tool internal |
| CC-20 | Tool execution time < 5s | Time measurement |
| CC-21 | Receive p99 < 50 ms | Benchmark T-29 |
| CC-22 | Verify p99 < 5 ms | Benchmark T-30 |
| CC-23 | Idempotency Redis SET NX used | grep |
| CC-24 | Stripe verifier rejects bad signature | T-04 |
| CC-25 | GitHub verifier rejects bad signature | T-08 |
| CC-26 | Internal verifier rejects bad signature | T-12 |
| CC-27 | Replay timestamp tolerance enforced | T-05 |
| CC-28 | Idempotent re-run | T-26 |
| CC-29 | Handler registry works via decorator | T-22 |
| CC-30 | DB unique constraint catches duplicate even if Redis cache TTL expired | T-15 |

---

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 12 Quality Standards enforced
- [ ] All 7 Invariants enforced
- [ ] All 25 User Stories pass acceptance tests
- [ ] All 30 Test Cases pass
- [ ] Tool is idempotent
- [ ] Tool is reversible
- [ ] Performance budget met
- [ ] Interaction with other tools verified
- [ ] All 15 edge cases handled
- [ ] Documentation updated
- [ ] Tool registered in `mcp_server.py`
- [ ] Re-audit by Opus in fresh context: ≥ 9.5/10

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-WR-01 | An incoming request without a valid signature NEVER reaches a handler | Verifier raises 400 before dispatch — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-04, T-08, T-12 |
| INV-WR-02 | The same `(provider, event_id)` is processed by handlers exactly once | Redis SET NX + DB unique constraint | T-15, T-21 |
| INV-WR-03 | A signed timestamp older than tolerance ALWAYS rejects | Stripe verifier checks `abs(now - ts) > tolerance` | T-05 |
| INV-WR-04 | Receive endpoint NEVER blocks on handler execution | Dispatched via ARQ enqueue — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-29 |
| INV-WR-05 | A 413 is returned BEFORE verification when body is too large | Length check first — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-13 |
| INV-WR-06 | Every received event is persisted (or marked duplicate) | CRUD writes a row in the same TX as enqueue | T-19 |
| INV-WR-07 | A handler exception ALWAYS marks the event `failed` and re-raises for ARQ retry | Worker `try/except/finally` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-23 |

---

## 9. User Stories

### 9.1 Signature verification & provider registry

**US-01: Accept a Stripe payment event with a valid HMAC signature**
- **As a** backend developer integrating Stripe Checkout into the application
- **I want** the webhook receiver to accept `payment_intent.succeeded` events from Stripe
- **So that** the order fulfilment handler fires automatically when a payment clears
- **Given:** `StripeVerifier` is registered in `_VERIFIERS`, `STRIPE_WEBHOOK_SECRET` is set in `.env`, and the Stripe signature header contains `t=<now>,v1=<correct-hmac>`
- **When:** Stripe POSTs to `POST /webhooks/incoming/stripe` with a body matching the signed payload
- **Then:**
  - Response status is 202 Accepted with body `{"status": "accepted"}`
  - One row is inserted into `inbound_webhooks` with `provider="stripe"`, `status="received"`
  - An ARQ job `process_inbound_webhook` is enqueued with the new row's UUID
  - `hmac.compare_digest` is used for the signature comparison (INV-WR-01, CC-24)

**US-02: Reject a Stripe event when the receiver's secret is wrong**
- **As a** security engineer auditing the webhook surface
- **I want** the endpoint to return 400 when the computed HMAC does not match `v1=` in the signature header
- **So that** a payload forged by an attacker without the shared secret is silently discarded
- **Given:** `STRIPE_WEBHOOK_SECRET` in the environment does not match the secret Stripe used to sign the event
- **When:** Stripe (or an attacker) POSTs to `/webhooks/incoming/stripe`
- **Then:**
  - Response status is 400 with detail `"Stripe signature mismatch"`
  - No row is inserted into `inbound_webhooks`
  - No ARQ job is enqueued
  - The comparison used `hmac.compare_digest`, not `==`, preventing timing-oracle attacks (INV-WR-01, T-04)

**US-03: Reject a Stripe event missing the Stripe-Signature header entirely**
- **As a** backend developer hardening the ingress pipeline
- **I want** the verifier to return 401 immediately when `Stripe-Signature` is absent
- **So that** misconfigured callers get a clear authentication error, not a cryptic 500
- **Given:** The incoming POST request has no `stripe-signature` header (headers are lowercased at ingress)
- **When:** Any client POSTs to `/webhooks/incoming/stripe` without that header
- **Then:**
  - Response status is 401 with detail `"Missing Stripe-Signature"`
  - `StripeVerifier.verify` raises `HTTPException(401)` before any HMAC computation
  - No DB row created (INV-WR-01, CC-02)

**US-04: Accept a GitHub push event with a valid X-Hub-Signature-256 header**
- **As a** DevOps engineer triggering CI pipelines from GitHub webhooks
- **I want** the receiver to accept `push` events from GitHub
- **So that** the deployment handler fires automatically on every merge to main
- **Given:** `GitHubVerifier` is registered, `GITHUB_WEBHOOK_SECRET` is set, and the request carries a correct `X-Hub-Signature-256: sha256=<hmac>` and `X-GitHub-Delivery` UUID
- **When:** GitHub POSTs to `POST /webhooks/incoming/github`
- **Then:**
  - Response status is 202 Accepted
  - `event_type` in the DB row equals the value from `X-GitHub-Event` header (e.g. `"push"`)
  - `provider_event_id` equals the `X-GitHub-Delivery` UUID
  - The row's `raw_headers` JSON contains `"x-hub-signature-256"` (CC-03, T-08)

**US-05: Reject a GitHub event with a tampered body**
- **As a** security engineer verifying signature enforcement for GitHub events
- **I want** a modified body to produce a 400 before any handler fires
- **So that** an attacker who intercepts a valid webhook and modifies the payload is blocked
- **Given:** A valid GitHub signature was computed against the original body, but the attacker changed one byte in the body before forwarding it
- **When:** The modified POST arrives at `/webhooks/incoming/github`
- **Then:**
  - `hmac.compare_digest` detects the mismatch and returns False
  - Response is 400 with detail `"GitHub signature mismatch"`
  - No ARQ job is enqueued and `inbound_webhooks` table is unchanged (INV-WR-01, CC-25, T-09)

### 9.2 Replay attack protection

**US-06: Reject a Stripe event whose timestamp is older than the tolerance window**
- **As a** security engineer blocking replay attacks on the payment endpoint
- **I want** any event with a timestamp more than 300 seconds in the past to be rejected
- **So that** an attacker who captured a legitimate signed payload cannot replay it hours later
- **Given:** `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE=300` and the `t=` field in `Stripe-Signature` is set to `int(time.time()) - 600` (10 minutes ago)
- **When:** The attacker POSTs the old-but-validly-signed event to `/webhooks/incoming/stripe`
- **Then:**
  - `abs(now - ts) > 300` evaluates to True inside `StripeVerifier.verify`
  - Response is 400 with detail `"Stripe signature timestamp out of tolerance"`
  - The check happens before HMAC comparison so the rejection is fast (INV-WR-03, T-05)

**US-07: Accept a Stripe event whose timestamp is within the tolerance window**
- **As a** backend developer validating that legitimate late-arriving events are not over-rejected
- **I want** events up to 295 seconds old to still be accepted
- **So that** minor network delays or provider retry queues do not produce false rejections
- **Given:** `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE=300` and the `t=` value is `int(time.time()) - 295`
- **When:** The signed POST arrives at `/webhooks/incoming/stripe`
- **Then:**
  - The timestamp check passes (`abs(now - ts) <= 300`)
  - Signature verification proceeds and succeeds
  - Response is 202 Accepted (CC-27, T-06)

**US-08: Tolerance window is configurable per deployment**
- **As a** platform engineer tuning security posture for a PCI-scoped service
- **I want** to set `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE=60` for stricter replay prevention
- **So that** the window is tightened to one minute without any code changes
- **Given:** `.env` sets `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE=60` and `Settings` reads this via `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE: int = 300`
- **When:** An event with `t=int(time.time()) - 120` arrives (2 minutes ago)
- **Then:**
  - `abs(now - ts) > 60` evaluates to True
  - Response is 400 — the stricter tolerance takes effect
  - The same verifier code works with no change (CC-13)

**US-09: Clock drift of a few seconds does not produce false rejections**
- **As a** backend developer dealing with infrastructure where server clocks drift slightly
- **I want** the timestamp check to tolerate a few seconds of clock skew between Stripe's servers and ours
- **So that** events signed at exactly `now` on Stripe's clock are not rejected due to 2-3 second drift
- **Given:** The event `t=` value is `int(time.time()) + 3` (3 seconds in the future due to clock drift)
- **When:** The event arrives and the tolerance is 300 seconds
- **Then:**
  - `abs(now - ts)` evaluates to 3, which is less than 300
  - The event is accepted and returns 202
  - Clock drift within the tolerance window is absorbed without special handling (INV-WR-03)

**US-10: A future timestamp far beyond tolerance is also rejected**
- **As a** security engineer blocking pre-computed replay payloads with future timestamps
- **I want** an event timestamped 1 hour in the future to be rejected
- **So that** an attacker cannot generate a signed payload today that remains valid for 60 minutes
- **Given:** The event carries `t=int(time.time()) + 3600` in the Stripe-Signature header
- **When:** The POST arrives at `/webhooks/incoming/stripe`
- **Then:**
  - `abs(now - ts)` is 3600, which exceeds the default tolerance of 300
  - Response is 400 with detail `"Stripe signature timestamp out of tolerance"`
  - The HMAC itself is never evaluated (INV-WR-03, T-05)

### 9.3 Idempotency & dedup

**US-11: A first-time event is accepted and enqueued**
- **As a** backend developer receiving a Stripe `charge.refunded` event for the first time
- **I want** the event to be persisted and dispatched exactly once
- **So that** the refund handler credits the customer's account without duplication
- **Given:** Redis contains no key `inbound:webhook:stripe:<event_id>` and `inbound_webhooks` has no matching row
- **When:** The signed POST arrives at `/webhooks/incoming/stripe` with `event.id="evt_001"`
- **Then:**
  - `claim_event("stripe", "evt_001")` calls `redis.set(key, "1", nx=True, ex=86400)` and returns True
  - A row is created with `status="received"` and `provider_event_id="evt_001"`
  - An ARQ job is enqueued — exactly one job (INV-WR-02, CC-05, T-15)

**US-12: A duplicate delivery from Stripe returns `{"status":"duplicate"}` without re-enqueueing**
- **As a** payment engineer handling Stripe's automatic retry on network timeout
- **I want** the second delivery of the same `charge.refunded` event to be silently absorbed
- **So that** the customer's account is not credited twice
- **Given:** `inbound:webhook:stripe:evt_001` already exists in Redis (SET NX was called at T+0)
- **When:** Stripe retries and POSTs the identical event at T+30s
- **Then:**
  - `claim_event` returns False (Redis NX rejected the duplicate key)
  - `crud_iwh.upsert_duplicate` records the duplicate in `inbound_webhooks` with `status="duplicate"`
  - No new ARQ job is enqueued — the handler does not fire a second time (INV-WR-02, CC-23, T-16)

**US-13: DB unique constraint catches a duplicate after Redis TTL expires**
- **As a** backend developer ensuring durability beyond the Redis cache window
- **I want** the `UNIQUE(provider, provider_event_id)` constraint to block a late duplicate even if the Redis key has expired
- **So that** a replay attack using a 25-hour-old event ID is blocked at the database layer
- **Given:** The Redis key `inbound:webhook:stripe:evt_001` has expired (TTL=86400s, event was received 25 hours ago) but the `inbound_webhooks` row still exists
- **When:** An attacker replays the event 25 hours later
- **Then:**
  - `claim_event` returns True (Redis has forgotten the key) and the code attempts DB insert
  - The `UNIQUE` constraint on `(provider, provider_event_id)` raises an IntegrityError
  - `crud_iwh.create_received` catches this and falls through to the duplicate path
  - Response is 200 with `{"status": "duplicate"}` (INV-WR-02, CC-30, T-19)

**US-14: Two providers may use the same event ID without collision**
- **As a** backend developer integrating both Stripe and GitHub
- **I want** `stripe:evt_001` and `github:evt_001` to be treated as independent events
- **So that** a short GitHub delivery UUID that happens to match a Stripe event ID does not cause false deduplication
- **Given:** Both `inbound:webhook:stripe:evt_001` and `inbound:webhook:github:evt_001` are absent from Redis
- **When:** Stripe sends `evt_001` and then GitHub independently sends delivery `evt_001`
- **Then:**
  - Both events produce Redis keys with different prefixes and neither blocks the other
  - Two distinct rows exist in `inbound_webhooks` with different `provider` values
  - Both respond 202 Accepted (T-21, CC-11)

**US-15: Idempotency TTL is controlled by `INBOUND_WEBHOOK_IDEMPOTENCY_TTL`**
- **As a** platform engineer reducing Redis memory pressure
- **I want** the Redis key TTL to respect the `INBOUND_WEBHOOK_IDEMPOTENCY_TTL` setting
- **So that** in high-volume deployments the operator can lower the window to 4 hours
- **Given:** `.env` sets `INBOUND_WEBHOOK_IDEMPOTENCY_TTL=14400` (4 hours)
- **When:** `claim_event("stripe", "evt_123")` is called
- **Then:**
  - The Redis command is `SET inbound:webhook:stripe:evt_123 1 NX EX 14400`
  - `EXPIRE` on the key confirms TTL is 14400 seconds
  - Events arriving after 4 hours can be re-processed (CC-13, T-20)

### 9.4 Async dispatch & performance

**US-16: Receive endpoint returns 202 in under 100 ms regardless of handler duration**
- **As a** Stripe integration engineer who needs the endpoint to respond within Stripe's 30-second timeout
- **I want** the HTTP response to be sent before the handler executes
- **So that** a slow business-logic handler (e.g. 10-second database aggregation) does not cause Stripe to retry
- **Given:** A `@webhook_handler("stripe", "invoice.paid")` handler that sleeps for 5 seconds is registered
- **When:** Stripe POSTs a valid signed event to `/webhooks/incoming/stripe`
- **Then:**
  - The endpoint calls `pool.enqueue_job("process_inbound_webhook", str(inbound.id))` and immediately returns
  - Response is 202 Accepted with total endpoint wall-time < 100 ms
  - The handler executes asynchronously in the ARQ worker process (INV-WR-04, CC-21, T-29)

**US-17: ARQ worker calls the registered handler with the reconstructed VerifiedEvent**
- **As a** backend developer writing a `payment_intent.succeeded` handler
- **I want** my handler to receive a `VerifiedEvent` with provider, event_id, event_type, and the full payload dict
- **So that** I can extract `event.payload["data"]["object"]["id"]` without re-parsing raw bytes
- **Given:** `@webhook_handler("stripe", "payment_intent.succeeded")` is registered and a row with `status="received"` exists in the DB
- **When:** ARQ executes `process_inbound_webhook(ctx, inbound_id)`
- **Then:**
  - `inbound.status` transitions to `"processing"` before the handler is called
  - The handler receives `VerifiedEvent(provider="stripe", event_id=..., event_type="payment_intent.succeeded", payload={...})`
  - After success, `inbound.status` is `"succeeded"` and `processed_at` is set to UTC now (CC-07, T-22)

**US-18: Multiple handlers for the same (provider, event_type) all execute in registration order**
- **As a** backend developer who needs both a fulfilment handler and an analytics handler for `payment_intent.succeeded`
- **I want** both handlers to fire when the event arrives
- **So that** I do not need to introduce an internal fan-out bus just to fan a single event type to two subsystems
- **Given:** Two functions are decorated with `@webhook_handler("stripe", "payment_intent.succeeded")` in module-load order
- **When:** A matching event is processed by the ARQ worker
- **Then:**
  - `get_handlers("stripe", "payment_intent.succeeded")` returns a list of 2 callables
  - Both are awaited sequentially in registration order
  - If both succeed, `inbound.status="succeeded"` (T-24)

**US-19: Signature verification completes in under 5 ms**
- **As a** backend developer benchmarking webhook ingress throughput
- **I want** the HMAC SHA-256 computation and constant-time compare to complete within 5 ms
- **So that** signature verification does not become the bottleneck at high event rates
- **Given:** A 1 KB Stripe payload is signed with a 32-byte secret
- **When:** `StripeVerifier.verify(body, headers)` is called 1000 times in a tight loop
- **Then:**
  - p99 latency is below 5 ms per call
  - The cost is dominated by `hashlib.sha256` which is implemented in C
  - Total receive endpoint overhead (verify + Redis + enqueue) stays under 50 ms p99 (CC-22, T-30)

**US-20: Body size cap is enforced before any cryptographic work**
- **As a** security engineer preventing denial-of-service via oversized payloads
- **I want** a 2 MB POST body to be rejected with 413 before the verifier or Redis are called
- **So that** an attacker cannot exhaust CPU with repeated giant HMAC computations
- **Given:** `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES=1048576` (1 MB) is set in settings
- **When:** A client POSTs a 2 MB body to `/webhooks/incoming/stripe`
- **Then:**
  - The route handler reads `body = await request.body()` and immediately checks `len(body) > settings.INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES`
  - Returns `JSONResponse({"detail": "Payload too large"}, status_code=413)`
  - No verifier is called, no Redis command is issued, no DB row is created (INV-WR-05, CC-13, T-13)

### 9.5 Audit, DLQ & edge cases

**US-21: Every accepted event is permanently recorded in `inbound_webhooks`**
- **As a** customer support engineer investigating a disputed Stripe charge
- **I want** to query `SELECT * FROM inbound_webhooks WHERE provider='stripe' AND provider_event_id='evt_001'` and find the exact payload that was received
- **So that** I can prove to the customer exactly when and what Stripe delivered
- **Given:** 100 distinct Stripe events were received over a 24-hour window
- **When:** A support engineer queries `inbound_webhooks` filtered by provider
- **Then:**
  - All 100 rows are present with correct `provider`, `event_type`, `payload`, `raw_headers`, and `received_at`
  - Rows with `status="duplicate"` are also present for retried deliveries
  - The `received_at` column has a timezone-aware timestamp (UTC) for each row (INV-WR-06, CC-09, T-27)

**US-22: A handler that raises an exception marks the event `failed` and triggers an ARQ retry**
- **As a** backend developer whose `charge.refunded` handler calls an external credit-note API that occasionally times out
- **I want** the failed event to remain in the database with `status="failed"` and be retried by ARQ
- **So that** a transient downstream outage does not permanently lose the refund
- **Given:** The registered handler raises `httpx.ConnectTimeout` on the first call
- **When:** ARQ executes `process_inbound_webhook(ctx, inbound_id)`
- **Then:**
  - The `except Exception` block sets `inbound.status="failed"`, `inbound.error=repr(exc)[:500]`, and `inbound.processed_at=now(UTC)`
  - The exception is re-raised so ARQ schedules a retry with its exponential backoff
  - On the next worker run the row is reprocessed (INV-WR-07, CC-07, T-23)

**US-23: After exhausting all ARQ retries the event lands in the dead-letter table**
- **As a** platform engineer operating a high-reliability payment service
- **I want** events that fail all retry attempts to be moved to a `webhook_events_dlq` table
- **So that** operators can inspect and manually replay them after the downstream system is restored
- **Given:** An ARQ job has retried `process_inbound_webhook` 3 times and the handler raises each time
- **When:** ARQ exhausts its retry budget and calls the `on_job_abort` hook
- **Then:**
  - A row is inserted into `webhook_events_dlq` with the original `inbound_webhook_id`, `provider`, `event_type`, and `error`
  - The original `inbound_webhooks` row has `status="failed"`
  - An operator can replay by calling `process_inbound_webhook(ctx, dlq_row.inbound_webhook_id)` directly (CC-17)

**US-24: A Shopify-compatible custom HMAC verifier can be added without modifying existing routes**
- **As a** backend developer onboarding a new Shopify store integration
- **I want** to add a `ShopifyVerifier(InboundVerifier)` and register it in `_VERIFIERS["shopify"]`
- **So that** the existing `/webhooks/incoming/{provider}` route immediately supports Shopify without any route or middleware changes
- **Given:** Shopify signs with `X-Shopify-Hmac-SHA256` base64-encoded and a custom tolerance check
- **When:** The developer adds `_VERIFIERS["shopify"] = ShopifyVerifier()` to `registry.py`
- **Then:**
  - `POST /webhooks/incoming/shopify` routes to the new verifier automatically via `get_verifier("shopify")`
  - A valid Shopify event returns 202 Accepted
  - An invalid signature returns 400 without any modifications to the route handler (CC-07, T-21)

**US-25: An operator can replay a dead-lettered event after the downstream system recovers**
- **As a** platform engineer whose external credit-note API was down for 2 hours
- **I want** to trigger reprocessing of all events in `webhook_events_dlq` from that window
- **So that** the backlog is cleared and all customers receive their refunds without manual intervention
- **Given:** 14 rows exist in `webhook_events_dlq` with `created_at` between T-120m and T-0m, all with `status="pending_replay"`
- **When:** The operator runs the management command `replay_dlq(provider="stripe", since=now-2h)`
- **Then:**
  - For each DLQ row, `process_inbound_webhook(ctx, row.inbound_webhook_id)` is enqueued in ARQ
  - DLQ rows are marked `status="replaying"` to prevent double-replay
  - On success each original `inbound_webhooks` row transitions to `status="succeeded"` (INV-WR-06)

## 10. Test Plan

### 10.1 Stripe verifier

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Valid Stripe signature | known secret + body | verify | VerifiedEvent |
| T-02 | Missing Stripe-Signature header | no header | verify | 401 |
| T-03 | Malformed signature header | "garbage" | verify | 400 |
| T-04 | Wrong signature | tampered body | verify | 400 |
| T-05 | Stale timestamp | ts > tolerance | verify | 400 |
| T-06 | Fresh timestamp accepted | ts within tolerance | verify | OK |
| T-07 | Stripe event without `id` field | missing | verify | KeyError → 400 |

### 10.2 GitHub & Internal verifiers

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-08 | GitHub valid signature | known secret | verify | OK |
| T-09 | GitHub bad signature | wrong | verify | 400 |
| T-10 | GitHub missing X-GitHub-Delivery | no header | verify | 400 |
| T-11 | GitHub event_type from header | X-GitHub-Event=push | verify | event_type=push |
| T-12 | Internal verifier OK | symmetric with sender | verify | OK |
| T-13 | Body too large 413 | 2 MB body | POST | 413 |
| T-14 | Unknown provider 404 | POST /webhooks/incoming/unknown | request | 404 |

### 10.3 Idempotency

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-15 | First event accepted | new id | POST | 202, accepted |
| T-16 | Duplicate returns duplicate | repeat | POST | 200, duplicate |
| T-17 | Duplicate does not enqueue | repeat | inspect ARQ | no new job |
| T-18 | Redis dedupe persists across processes | publish from another process | POST | duplicate |
| T-19 | DB UNIQUE blocks even if Redis TTL expired | clear Redis | POST same id | duplicate via DB path |
| T-20 | TTL is configurable | set 60s | inspect EXPIRE | 60 |
| T-21 | Different providers same event_id allowed | stripe id=x, github id=x | both POST | both accepted |

### 10.4 Handler dispatch

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-22 | Handler called via decorator | register handler, send event | worker | handler called |
| T-23 | Handler exception → failed | handler raises | worker | status=failed, error set |
| T-24 | Multiple handlers all called | 2 registered | worker | both called |
| T-25 | Unknown event type → succeeded with no handler | no registered | worker | succeeded |

### 10.5 Performance & idempotency

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-26 | Tool re-run no-op | installed | run | no changes |
| T-27 | Receive endpoint persists raw_headers | POST | inspect | headers JSON present |
| T-28 | Receive returns 202 not 200 | accepted | inspect status | 202 |
| T-29 | Receive p99 < 50 ms | benchmark | measure | < 50 ms |
| T-30 | Verify p99 < 5 ms | benchmark | measure | < 5 ms |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_webhook_sender` | No | ✅ Compatible | Internal verifier reuses the sender's `verify_signature`. Symmetric. |
| `add_outbox_pattern` | No | ✅ Compatible | Handlers can write to outbox to publish derived events. |
| `add_audit_log` | No | ⚠️ Caveat | Inbound webhook table is the audit; do NOT also audit each row in the global audit log to avoid duplication. |
| `add_multi_tenancy` | No | ⚠️ Caveat | Inbound events are typically pre-tenant (e.g. Stripe doesn't know our tenants); handlers must look up the tenant from the event payload. |
| `add_rbac` | No | ✅ Compatible | Handlers run as system actor; permissions don't apply. |
| `add_rate_limit` | No | ⚠️ Caveat | Don't aggressively rate-limit the inbound endpoint or you'll trigger provider retries; whitelist provider IPs instead. |
| `add_circuit_breaker` | No | ✅ Compatible | Independent. |
| `add_long_running_task` | No | ✅ Compatible | Handlers can spawn long-running tasks. |
| `add_sse` | No | ✅ Compatible | Handlers can publish SSE events to user channels. |
| TOOL-034 performance_baseline | downstream | `POST /webhooks/inbound/{provider}` throughput and p99 are captured in the baseline (target p99 < 100 ms, throughput ≥ 200 rps) so a change to `app/core/inbound_webhooks/idempotency.py` `claim_event` that increases DB lock contention does not silently degrade the inbound path under load |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_webhook_receiver` is installed but no `add_outbox_pattern` is present and recommends TOOL-022 `add_outbox_pattern` so that `process_inbound_webhook` in `app/workers/inbound_webhook_worker.py` can publish derived events transactionally without dual-write risk |
| TOOL-029 security_scan | downstream | `app/core/inbound_webhooks/providers/stripe.py` and `app/core/inbound_webhooks/providers/github.py` are scanned for timing-attack patterns (must use `hmac.compare_digest` not string equality) and for raw `hmac.new(...)` calls missing the correct `digestmod` argument; any CRITICAL finding blocks merge |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/webhook_inbound.py app/core/inbound_webhooks \
  app/workers/inbound_webhook_worker.py app/crud/inbound_webhook.py \
  app/api/routes/inbound_webhooks.py app/schemas/inbound_webhook.py \
  app/api/main.py app/core/config.py
rm alembic/versions/*_add_webhook_receiver.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `inbound_webhooks` table.

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_webhook_receiver.py`
- Drop partially-created table
- Re-run

### Emergency: a provider is flooding us
1. Block provider at the load balancer
2. OR set `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES = 1` to fast-fail (returns 413 cheaply)
3. Investigate `inbound_webhooks` table to identify abuse pattern
4. Consider IP whitelist at the load balancer

### Emergency: secret rotated by provider mid-flight
1. Add new secret to settings via env var rotation (use SettingsList if needed)
2. Verifier tries new secret first, falls back to old (out of scope for default impl; document)
3. After 1 hour, remove old secret


### Failure mode: tool partially modified files
If the generator crashed halfway and left an inconsistent tree (some modules present, others missing, config half-written), restore to a clean HEAD before re-running:
```bash
# 1. Inspect what changed vs HEAD
git status --short

# 2. Revert tool-written files + drop freshly-created ones
git checkout HEAD -- app/ tests/ alembic/ pyproject.toml
git clean -fd app/ tests/

# 3. Verify clean tree before re-running
git diff HEAD --exit-code && echo "clean" || echo "DIRTY — stop"
```

### Failure mode: Stripe signing secret rotation or ARQ handler exception loop
```bash
# ── Step 1: Detect handler exception loop in ARQ ───────────────────────────
# Tail the ARQ worker logs for recurring tracebacks on the same job function
kubectl logs -l app=arq-worker --tail=200 | grep -A5 "Exception in"

# Check if a specific event_type is looping (all entries have same type + error)
psql "$DATABASE_URL" -c "
  SELECT event_type, error_message, COUNT(*) AS occurrences
  FROM inbound_webhooks
  WHERE status = 'failed'
    AND created_at > NOW() - INTERVAL '1 hour'
  GROUP BY event_type, error_message
  ORDER BY occurrences DESC
  LIMIT 10;
"

# ── Step 2: Disable the looping handler without taking the route down ──────
# Set env var WEBHOOK_HANDLER_<EVENT_TYPE>_ENABLED=false (app reads at startup)
# e.g. for payment_intent.succeeded:
kubectl set env deployment/arq-worker WEBHOOK_HANDLER_PAYMENT_INTENT_SUCCEEDED_ENABLED=false
kubectl rollout restart deployment/arq-worker

# ── Step 3: Stripe signing secret rotation procedure ──────────────────────
# 1. Get new secret from Stripe dashboard (Webhooks → endpoint → rotate)
# 2. Deploy the new secret BEFORE the old one expires (grace period = 72h)
kubectl create secret generic stripe-webhook \
  --from-literal=STRIPE_WEBHOOK_SECRET="whsec_<NEW_SECRET>" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/api

# 3. Verify the new secret validates correctly against a Stripe test event:
curl -X POST https://your-api.example.com/webhooks/stripe \
  -H "Content-Type: application/json" \
  -H "Stripe-Signature: $(stripe trigger payment_intent.succeeded --output headers | grep Stripe-Signature)" \
  -d '{"type":"payment_intent.succeeded"}'
# Expect: HTTP 202

# 4. Confirm old test events now return 400 (signature expired):
# Wait for Stripe's 5-minute window to pass, then replay an old event ID
# via Stripe CLI: stripe events resend <evt_old_id>
# Expect: HTTP 400 Signature verification failed

# ── Step 4: Verify idempotency cache (Redis) is up ─────────────────────────
redis-cli -u "$REDIS_URL" PING
# If Redis is down, idempotency falls back to DB UNIQUE constraint (slower but safe)
# Check for duplicate processing that may have slipped through:
psql "$DATABASE_URL" -c "
  SELECT provider, event_id, COUNT(*) AS cnt
  FROM inbound_webhooks
  WHERE created_at > NOW() - INTERVAL '30 minutes'
  GROUP BY provider, event_id
  HAVING COUNT(*) > 1;
"
```

### Emergency: Redis idempotency cache down or DLQ full
```bash
# ── Step 1: Confirm Redis is unreachable ───────────────────────────────────
redis-cli -u "$REDIS_URL" PING   # returns NOAUTH / Connection refused / timeout

# ── Step 2: Engage DB-only idempotency mode ────────────────────────────────
# The receiver's verify_idempotency() should degrade gracefully.
# Force it by setting WEBHOOK_IDEMPOTENCY_BACKEND=db (skips Redis entirely):
kubectl set env deployment/api WEBHOOK_IDEMPOTENCY_BACKEND=db
kubectl rollout status deployment/api --timeout=90s

# Confirm no duplicate inserts sneak through (check UNIQUE constraint):
psql "$DATABASE_URL" -c "
  SELECT provider, event_id FROM inbound_webhooks
  GROUP BY provider, event_id HAVING COUNT(*) > 1;
"
# Should return 0 rows.

# ── Step 3: Inspect full DLQ (status=failed, not retried) ──────────────────
psql "$DATABASE_URL" -c "
  SELECT id, provider, event_type, error_message,
         attempt_count, created_at
  FROM inbound_webhooks
  WHERE status = 'failed'
  ORDER BY created_at DESC
  LIMIT 50;
"

# ── Step 4: Drain the DLQ once dependency is restored ──────────────────────
# Reset failed events to 'pending' so ARQ re-processes them
psql "$DATABASE_URL" -c "
  UPDATE inbound_webhooks
  SET status = 'pending', attempt_count = 0
  WHERE status = 'failed'
    AND created_at > NOW() - INTERVAL '24 hours';
"

# ── Step 5: Restore Redis and switch back ──────────────────────────────────
# After Redis is healthy, revert to Redis-backed idempotency:
kubectl set env deployment/api WEBHOOK_IDEMPOTENCY_BACKEND=redis
kubectl rollout status deployment/api --timeout=90s

# Verify cache entries are being written for new events:
redis-cli -u "$REDIS_URL" KEYS "webhook:idempotency:*" | head -5
```


---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no Redis or ARQ | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | Provider secret missing in env | Verifier raises at startup; the operation returns a structured error response and no side effects persist |
| EC-3 | Provider sends content-type other than application/json | Verifier still works (it operates on raw bytes); JSON parse fails → 400 |
| EC-4 | Provider sends gzipped body | uvicorn handles content-encoding; verifier sees decoded bytes; signature must be over decoded bytes (depends on provider; document) |
| EC-5 | Provider retries before our 202 response arrives (slow LB) | Idempotency cache absorbs the second attempt |
| EC-6 | Same event_id from different providers | Allowed (UNIQUE is on (provider, event_id)) |
| EC-7 | Provider sends event_id we never processed (cache cold) | Treated as new; processed normally |
| EC-8 | DB unique constraint race between two workers | One INSERT wins; other gets IntegrityError → marked duplicate |
| EC-9 | Handler is sync (not async) | Tool documents that handlers MUST be async; raises at registration time |
| EC-10 | Handler runs longer than ARQ job_timeout | ARQ kills the job; status stays processing; admin must retry |
| EC-11 | Tool installed without webhook_sender | Internal verifier still works if `app/core/webhooks/signer.py` is present; otherwise tool warns |
| EC-12 | Multi-tenant project; event payload doesn't carry tenant_id | Handler must figure it out (e.g. by Stripe customer_id → user lookup); document |
| EC-13 | Stripe sends an event we don't recognize | Status=succeeded with no handler; visible in DB for debugging |
| EC-14 | Receive endpoint behind nginx with body limit smaller than ours | nginx 413 fires first; receiver never sees the request |
| EC-15 | Provider IP changes; our firewall blocks | Document the need for an IP-allowlist refresh in next_steps |

---

## 14. Acceptance Criteria

1. ✅ All 30 CC verified
2. ✅ All 25 user stories pass
3. ✅ All 30 tests pass
4. ✅ All 7 invariants enforced
5. ✅ All 15 edge cases handled
6. ✅ Interaction matrix verified
7. ✅ Rollback procedure tested
8. ✅ Performance SLOs met
9. ✅ Re-audit by Opus: ≥ 9.5/10
10. ✅ One human dev points Stripe CLI test events at the receiver, sees them processed, and verifies idempotency by re-sending

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate Alembic initialized
- [ ] Validate Redis and ARQ configured
- [ ] Detect existing `inbound_webhooks` table → idempotent skip if found
- [ ] Assert pre-flight raises `MissingConfigError` when `STRIPE_WEBHOOK_SECRET` is absent and Stripe is a requested provider via `test_preflight.py::test_missing_stripe_secret_raises`
- [ ] Assert pre-flight returns `{"skipped": true}` when `inbound_webhooks` table already exists via `test_preflight.py::test_idempotent_skip_when_table_exists`
- [ ] Run `ruff check app/core/inbound_webhooks/` after generation — zero new findings

### 15.2 Settings
- [ ] Add `INBOUND_WEBHOOK_IDEMPOTENCY_TTL: int = 86400`
- [ ] Add `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE: int = 300`
- [ ] Add `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES: int = 1_048_576`
- [ ] Per provider: `STRIPE_WEBHOOK_SECRET`, `GITHUB_WEBHOOK_SECRET`, `INTERNAL_WEBHOOK_SECRET`
- [ ] Add to `.env.example`
- [ ] Assert `INBOUND_WEBHOOK_SIGNATURE_TOLERANCE` env override is read and applied by the Stripe verifier via `test_settings.py::test_signature_tolerance_env_override`
- [ ] Assert `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES` env override is respected by the route body-size check via `test_settings.py::test_max_payload_bytes_env_override`

### 15.3 Verifier base + providers
- [ ] Create `app/core/inbound_webhooks/base.py`
- [ ] Create `app/core/inbound_webhooks/providers/stripe.py` (or other providers per `providers` param)
- [ ] Create `app/core/inbound_webhooks/providers/github.py`
- [ ] Create `app/core/inbound_webhooks/providers/internal.py`
- [ ] Verify files parse
- [ ] Assert Stripe-format signature with a timestamp 6 min old is rejected via `test_replay.py::test_stripe_signature_timestamp_rejected_at_6min_old`
- [ ] Assert GitHub HMAC-SHA256 signature is verified correctly using a known secret/body pair via `test_providers.py::test_github_hmac_signature_accepted_for_known_pair`
- [ ] Assert `base.py` `verify` raises `SignatureVerificationError` for a tampered body via `test_providers.py::test_tampered_body_raises_signature_verification_error`

### 15.4 Registry
- [ ] Create `app/core/inbound_webhooks/registry.py`
- [ ] Implement `get_verifier`, `webhook_handler` decorator, `get_handlers`
- [ ] Verify file parses
- [ ] Assert `get_verifier("stripe")` returns the `StripeVerifier` instance via `test_registry.py::test_get_verifier_returns_stripe_instance`
- [ ] Assert `@webhook_handler("stripe", "payment_intent.succeeded")` registers exactly one handler via `test_registry.py::test_webhook_handler_decorator_registers_handler`
- [ ] Run `mypy --strict app/core/inbound_webhooks/registry.py` — zero errors

### 15.5 Idempotency
- [ ] Create `app/core/inbound_webhooks/idempotency.py`
- [ ] Implement `claim_event` with `SET NX EX`
- [ ] Verify file parses
- [ ] Assert `claim_event` returns `True` on first call and `False` on second call for the same event ID via `test_idempotency.py::test_claim_event_single_use`
- [ ] Assert the Redis key TTL is set to `INBOUND_WEBHOOK_IDEMPOTENCY_TTL` seconds via `test_idempotency.py::test_claim_event_sets_correct_ttl`
- [ ] Run `ruff check app/core/inbound_webhooks/idempotency.py` — zero findings

### 15.6 Model
- [ ] Create `app/models/webhook_inbound.py`
- [ ] UniqueConstraint + CheckConstraint
- [ ] Verify file parses
- [ ] Assert `UniqueConstraint` on `(provider, event_id)` prevents duplicate ingestion via `test_models_inbound.py::test_duplicate_event_id_raises_integrity_error`
- [ ] Assert `CheckConstraint` on `status` rejects values outside `{pending, processing, processed, failed}` via `test_models_inbound.py::test_invalid_status_rejected_by_check_constraint`
- [ ] Run `ruff check app/models/webhook_inbound.py` and `mypy app/models/webhook_inbound.py` — zero findings

### 15.7 CRUD
- [ ] Create `app/crud/inbound_webhook.py` with create_received, get, upsert_duplicate
- [ ] Verify file parses via `python -c "import app.crud.inbound_webhook"` and all public helpers are exported
- [ ] Assert `create_received` persists a row with `status="pending"` and the raw payload via `test_crud_inbound.py::test_create_received_persists_pending_row`
- [ ] Assert `upsert_duplicate` increments `duplicate_count` without inserting a new row via `test_crud_inbound.py::test_upsert_duplicate_increments_count`
- [ ] Add trace span `inbound_webhook.crud.create_received` with tags `provider` and `event_type` for observability
- [ ] Assert `get_by_event_id` is provider-scoped via `test_crud_inbound.py::test_get_by_event_id_respects_provider_column` (same event_id under different providers returns distinct rows)
- [ ] Assert `mark_processed` sets `processed_at` and flips `status` from `pending` to `processed` atomically in a single UPDATE via `test_crud_inbound.py::test_mark_processed_atomic`

### 15.8 Schemas
- [ ] Create `app/schemas/inbound_webhook.py` with InboundWebhookPublic, etc.
- [ ] Verify file parses and all models import cleanly from `app.schemas.inbound_webhook`
- [ ] Assert `InboundWebhookPublic` excludes raw `payload` field from serialisation via `test_schemas_inbound.py::test_inbound_webhook_public_excludes_raw_payload`
- [ ] Assert `InboundWebhookPublic.status` is validated as a `Literal` enum via `test_schemas_inbound.py::test_inbound_webhook_status_literal_validation`
- [ ] Add structlog `{"event": "inbound_webhook_persisted", "provider": ..., "event_type": ...}` in `create_received`
- [ ] Assert the `InboundWebhookCreate` request schema rejects payloads larger than `INBOUND_WEBHOOK_MAX_BODY_BYTES` via a Pydantic `max_length` validator + `test_schemas_inbound.py::test_oversized_payload_rejected`
- [ ] Assert `InboundWebhookPublic.response_dump()` redacts any field present in `INBOUND_WEBHOOK_REDACT_FIELDS` env var via `test_schemas_inbound.py::test_redacted_fields_never_serialized`

### 15.9 Routes
- [ ] Create `app/api/routes/inbound_webhooks.py`
- [ ] POST /webhooks/incoming/{provider}
- [ ] Body size check, verifier, dedupe, persist, enqueue
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Assert `POST /webhooks/incoming/stripe` with a valid signature returns 200 and enqueues an ARQ job via `test_routes_inbound.py::test_valid_stripe_webhook_accepted_and_enqueued`
- [ ] Assert `POST /webhooks/incoming/stripe` with an invalid signature returns 400 without persisting anything via `test_routes_inbound.py::test_invalid_signature_returns_400_no_persist`
- [ ] Assert body larger than `INBOUND_WEBHOOK_MAX_PAYLOAD_BYTES` returns 413 via `test_routes_inbound.py::test_oversized_payload_returns_413`

### 15.10 Worker
- [ ] Create `app/workers/inbound_webhook_worker.py`
- [ ] Implement `process_inbound_webhook`
- [ ] Verify file parses
- [ ] Assert `process_inbound_webhook` calls the registered handler for the event type via `test_worker_inbound.py::test_process_calls_registered_handler`
- [ ] Assert `process_inbound_webhook` sets `status="processed"` on success and `status="failed"` on handler exception via `test_worker_inbound.py::test_process_sets_correct_status`
- [ ] Run `ruff check app/workers/inbound_webhook_worker.py` — zero findings

### 15.11 Migration
- [ ] Generate `0NNN_add_webhook_receiver.py`
- [ ] `upgrade()` creates table + indexes + constraints
- [ ] `downgrade()` drops in reverse
- [ ] Verify migration parses
- [ ] Assert `alembic upgrade head` + `alembic downgrade -1` completes cleanly on a blank schema via `test_migrations.py::test_webhook_receiver_migration_roundtrip`
- [ ] Assert the `UniqueConstraint` on `(provider, event_id)` is present in the upgraded schema via `test_migrations.py::test_unique_constraint_exists_after_upgrade`
- [ ] Run `ruff check alembic/versions/0NNN_add_webhook_receiver.py` — zero findings

### 15.12 Test generation
- [ ] Create `tests/test_webhook_receiver.py` with all 30 tests
- [ ] Use known signature/secret pairs to generate valid signatures
- [ ] Use `respx` if needed
- [ ] Verify file parses
- [ ] Assert overall line coverage for `app/core/inbound_webhooks/` is ≥ 90% via `pytest --cov=app.core.inbound_webhooks --cov-fail-under=90`
- [ ] Assert `test_webhook_receiver.py::test_replay_attack_rejected` uses a 6-min-old Stripe timestamp to confirm replay rejection
- [ ] Run `ruff check tests/test_webhook_receiver.py` — zero findings

### 15.13 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created table on failure
- [ ] Assert mid-run failure leaves no partial files under `app/core/inbound_webhooks/` via `test_atomicity.py::test_rollback_removes_partial_files`
- [ ] Assert returned dict lists every rolled-back file path via `test_atomicity.py::test_error_response_lists_rolled_back_files`
- [ ] Run `mypy app/core/inbound_webhooks/` — zero errors after rollback path changes

### 15.14 Documentation
- [ ] Append webhook receiver section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Assert `manifest.yaml` entry for `add_webhook_receiver` contains `inputs`, `outputs`, and `idempotent: true` fields via `test_manifest.py::test_webhook_receiver_tool_manifest_schema`
- [ ] Assert `SKILL.md` tools table row for TOOL-016 links to this spec file via `test_skill_md.py::test_tool_016_row_exists_with_spec_link`
- [ ] Run `ruff check mcp_server.py` — zero new findings after the update

### 15.15 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure receive p99 latency
- [ ] Measure verify p99 latency

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/webhook_inbound.py",
    "app/core/inbound_webhooks/__init__.py",
    "app/core/inbound_webhooks/base.py",
    "app/core/inbound_webhooks/registry.py",
    "app/core/inbound_webhooks/idempotency.py",
    "app/core/inbound_webhooks/providers/__init__.py",
    "app/core/inbound_webhooks/providers/stripe.py",
    "app/core/inbound_webhooks/providers/github.py",
    "app/core/inbound_webhooks/providers/internal.py",
    "app/crud/inbound_webhook.py",
    "app/schemas/inbound_webhook.py",
    "app/api/routes/inbound_webhooks.py",
    "app/workers/inbound_webhook_worker.py",
    "alembic/versions/0016_add_webhook_receiver.py",
    "tests/test_webhook_receiver.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py",
    ".env.example"
  ],
  "metrics": {
    "execution_time_ms": 4587,
    "files_changed": 18,
    "lines_added": 1241,
    "lines_removed": 3,
    "providers_installed": ["stripe", "github", "internal"],
    "idempotency_ttl_seconds": 86400,
    "signature_tolerance_seconds": 300,
    "max_payload_bytes": 1048576
  },
  "next_steps": [
    "Set per-provider secrets: STRIPE_WEBHOOK_SECRET, GITHUB_WEBHOOK_SECRET, INTERNAL_WEBHOOK_SECRET",
    "Run: alembic upgrade head",
    "Run: pytest tests/test_webhook_receiver.py -v",
    "Start the ARQ worker: `arq app.workers.inbound_webhook_worker.WorkerSettings`",
    "Register a handler: `@webhook_handler('stripe', 'payment_intent.succeeded')` then `async def on_payment(event): ...`",
    "Test locally with `stripe listen --forward-to http://localhost:8000/api/v1/webhooks/incoming/stripe`"
  ],
  "warnings": [
    "Inbound events are at-least-once. Handlers MUST be idempotent (the dedupe cache and DB constraint help, but handlers can still be invoked twice if a worker crashes mid-process).",
    "Provider IP allowlisting is recommended at the load balancer (especially for high-traffic providers).",
    "Handlers run in the background. The provider sees a fast 202; if your handler is slow or fails, the receiver still returned success."
  ],
  "notes": [
    "Webhook receiver installed for providers: stripe, github, internal.",
    "Idempotency: Redis SET NX (24h TTL) + DB UNIQUE(provider, provider_event_id).",
    "Stripe signature tolerance: 300s.",
    "Max payload: 1 MB.",
    "Existing tests still pass: 66/66."
  ]
}
```
