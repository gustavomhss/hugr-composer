# TOOL-015: add_webhook_sender

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_webhook_sender` |
| Category | EXTEND > Real-time |
| Complexity | High |
| Dependencies | Existing project with auth, Alembic, Redis (queue), ARQ (background worker), httpx |
| Signature | `add_webhook_sender(project_dir: str, max_attempts: int = 7, http_timeout_seconds: float = 10.0, max_payload_bytes: int = 262_144, disable_after_consecutive_failures: int = 12) -> dict` |
| Parameters | `project_dir`: project root path<br>`max_attempts`: total delivery attempts including the first<br>`http_timeout_seconds`: per-request HTTP timeout<br>`max_payload_bytes`: hard cap on event payload size<br>`disable_after_consecutive_failures`: auto-disable endpoint after this many consecutive failures |

---

## 2. Purpose

The `fastapi_add_webhook_sender` tool adds outbound webhook delivery so the application can notify third-party systems of business events — `item.created`, `order.paid`, `payment.refunded`, `user.signed_up` — over plain HTTP without every caller having to rebuild signature calculation, retry backoff, delivery persistence, and dead-letter handling. Every serious product eventually needs webhooks because consumers want push notifications rather than polling, but a correct implementation has to guarantee at-least-once delivery under crashes, survive partner outages, sign every payload so the receiver can verify authenticity, expose enough observability for customer support to debug "I never got my webhook" tickets, and protect the sender from amplifying its own outages into partner systems.

Each subscribed endpoint receives a signed POST whose body is the deterministically-serialized event payload and whose `X-Signature` header is a Stripe-style HMAC-SHA256 of `f"{ts}.{body}"` (format `t=<unix_ts>,v1=<hex>`) so receivers can verify authenticity and reject replays with a 5-minute window. Failed deliveries retry with a fixed exponential schedule (1s → 5s → 30s → 5m → 1h → 6h → 24h, 7 attempts totaling ~32 hours) so partners have ample time to recover from an outage without the sender hammering them. Key design decisions: endpoints with more than 12 consecutive failures auto-disable and page the operator via TOOL-041 error_rate_analyzer so a dead partner does not keep wasting worker cycles; every attempt is persisted in a `webhook_attempts` table for audit and customer-support debugging; the app-facing surface is a single helper (`await send_webhook("event.name", payload)`) that enqueues the work to an ARQ worker so callers never block; and the payload is JSON-serialized with `sort_keys=True, separators=(",",":")` so the signature is byte-stable across any serializer rework.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Dev waits in CLI |
| Files modified | ≤ 5 global files | Predictability |
| Files created | ≥ 11 (2 models, sender, signer, worker, deps, crud, routes, schemas, migration, tests) | Predictability |
| `send_webhook` enqueue latency | < 5 ms | ARQ enqueue is a single Redis call |
| First-attempt dispatch latency | < 1s after enqueue | Worker poll interval |
| HTTP request timeout | 10s | Configurable |
| Worker throughput | ≥ 100 deliveries/sec/worker | Async httpx + connection pool |
| Backoff schedule | 1s, 5s, 30s, 300s, 3600s, 21600s, 86400s | Predictable, bounded total time |
| Migration runtime | < 5s | 2 new tables |
| Memory overhead | < 10 MB per worker | httpx connection pool + ARQ |

---

## 4. Code Examples (Before / After)

### 4.1 Models (NEW)
```python
# app/models/webhook.py
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
import uuid


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    events: Mapped[list] = mapped_column(JSON, nullable=False, server_default="[]")
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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
            "url ~ '^https?://.+'",
            name="ck_webhook_endpoints_url_format",
        ),
    )


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(127), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    endpoint: Mapped[WebhookEndpoint] = relationship(back_populates="deliveries")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','succeeded','failed','dead')",
            name="ck_webhook_deliveries_status",
        ),
    )
```

### 4.2 Signer (NEW)
```python
# app/core/webhooks/signer.py
import hashlib
import hmac
import time


def sign_payload(secret: str, body_bytes: bytes, timestamp: int | None = None) -> str:
    """
    Returns a Stripe-style signature header value:
        t=<unix_seconds>,v1=<hex hmac sha256 of "<t>.<body>">
    """
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode("ascii") + body_bytes
    sig = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def verify_signature(secret: str, body_bytes: bytes, header_value: str, tolerance_seconds: int = 300) -> bool:
    """
    Constant-time verification. Used by webhook RECEIVERS (companion tool).
    Included here for symmetry; receivers should reuse this function.
    """
    parts = dict(p.split("=", 1) for p in header_value.split(",") if "=" in p)
    try:
        ts = int(parts.get("t", 0))
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > tolerance_seconds:
        return False
    expected = sign_payload(secret, body_bytes, timestamp=ts).split(",")[1].split("=", 1)[1]
    actual = parts.get("v1", "")
    return hmac.compare_digest(expected, actual)
```

### 4.3 Backoff schedule (NEW)
```python
# app/core/webhooks/backoff.py
# Total = ~32h across 7 attempts.
ATTEMPT_DELAYS_SECONDS = [
    0,        # attempt 1: immediate
    1,        # attempt 2: 1s after attempt 1 fails
    5,        # attempt 3: 5s after attempt 2 fails
    30,       # attempt 4
    300,      # attempt 5
    3600,     # attempt 6
    21600,    # attempt 7
]


def delay_for_attempt(attempt_number: int) -> int:
    """attempt_number is 1-indexed; returns 0 for the first dispatch."""
    if attempt_number < 1 or attempt_number > len(ATTEMPT_DELAYS_SECONDS):
        return -1
    return ATTEMPT_DELAYS_SECONDS[attempt_number - 1]
```

### 4.4 Worker (NEW)
```python
# app/workers/webhook_worker.py
import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.webhooks.backoff import delay_for_attempt
from app.core.webhooks.signer import sign_payload
from app.crud import webhook as crud_wh

logger = logging.getLogger(__name__)


async def deliver_webhook(ctx: dict, delivery_id: str) -> None:
    """
    ARQ task: load delivery, attempt HTTP POST, persist outcome,
    enqueue retry if needed, auto-disable endpoint on too many failures.
    """
    async with async_session_maker() as session:
        delivery = await crud_wh.get_delivery(session, id=delivery_id)
        if not delivery or delivery.status not in ("pending",):
            return
        endpoint = await crud_wh.get_endpoint(session, id=delivery.endpoint_id)
        if not endpoint or endpoint.status != "active":
            delivery.status = "dead"
            await session.commit()
            return

        delivery.attempt_number += 1
        body_bytes = json.dumps(delivery.payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = sign_payload(endpoint.secret, body_bytes)

        try:
            async with httpx.AsyncClient(timeout=settings.WEBHOOK_HTTP_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    endpoint.url,
                    content=body_bytes,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature": signature,
                        "X-Event-Id": str(delivery.event_id),
                        "X-Event-Type": delivery.event_type,
                        "X-Attempt": str(delivery.attempt_number),
                        "User-Agent": f"{settings.PROJECT_NAME}-webhooks/1.0",
                    },
                )
            delivery.http_status = resp.status_code
            delivery.response_body = resp.text[:4096]

            if 200 <= resp.status_code < 300:
                delivery.status = "succeeded"
                delivery.delivered_at = datetime.now(timezone.utc)
                endpoint.last_success_at = delivery.delivered_at
                endpoint.consecutive_failures = 0
            else:
                _handle_failure(delivery, endpoint, error=f"HTTP {resp.status_code}")
        except (httpx.RequestError, httpx.TimeoutException) as exc:
            _handle_failure(delivery, endpoint, error=repr(exc))

        await session.commit()

    if delivery.status == "pending":
        # Schedule retry
        next_delay = delay_for_attempt(delivery.attempt_number + 1)
        if next_delay >= 0:
            await ctx["redis"].enqueue_job(
                "deliver_webhook",
                str(delivery.id),
                _defer_by=next_delay,
            )


def _handle_failure(delivery, endpoint, error: str) -> None:
    delivery.error = error[:500]
    endpoint.consecutive_failures += 1
    endpoint.last_failure_at = datetime.now(timezone.utc)

    if delivery.attempt_number >= settings.WEBHOOK_MAX_ATTEMPTS:
        delivery.status = "dead"
    else:
        delivery.status = "pending"

    if endpoint.consecutive_failures >= settings.WEBHOOK_DISABLE_AFTER_FAILURES:
        endpoint.status = "disabled"
        delivery.status = "dead"


class WorkerSettings:
    functions = [deliver_webhook]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    job_timeout = settings.WEBHOOK_HTTP_TIMEOUT_SECONDS + 5
    max_jobs = 100
```

### 4.5 Public API (NEW)
```python
# app/core/webhooks/sender.py
import json
import logging
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.db import async_session_maker
from app.core.queue import get_arq_pool
from app.crud import webhook as crud_wh

logger = logging.getLogger(__name__)


async def send_webhook(event_type: str, payload: dict[str, Any]) -> int:
    """
    Public helper. Looks up active endpoints subscribed to `event_type`,
    creates a Delivery row for each, and enqueues the worker job.

    Returns the number of deliveries enqueued.
    """
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    if len(body.encode("utf-8")) > settings.WEBHOOK_MAX_PAYLOAD_BYTES:
        raise ValueError("Webhook payload too large")

    event_id = uuid4()

    async with async_session_maker() as session:
        endpoints = await crud_wh.list_endpoints_for_event(session, event_type=event_type)
        if not endpoints:
            return 0
        deliveries = []
        for ep in endpoints:
            d = await crud_wh.create_delivery(
                session,
                endpoint_id=ep.id,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
            )
            deliveries.append(d)
        await session.commit()

    pool = await get_arq_pool()
    for d in deliveries:
        await pool.enqueue_job("deliver_webhook", str(d.id))
    return len(deliveries)
```

### 4.6 Routes (admin) — NEW
```python
# app/api/routes/webhooks.py
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.crud import webhook as crud_wh
from app.schemas.webhook import (
    WebhookCreate,
    WebhookDeliveryPublic,
    WebhookEndpointPublic,
    WebhookUpdate,
)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/", response_model=WebhookEndpointPublic, status_code=201)
async def create_webhook(in_: WebhookCreate, session: SessionDep, current_user: CurrentUser):
    return await crud_wh.create_endpoint(session, in_=in_, user_id=current_user.id)


@router.get("/", response_model=list[WebhookEndpointPublic])
async def list_my_webhooks(session: SessionDep, current_user: CurrentUser):
    return await crud_wh.list_endpoints_for_user(session, user_id=current_user.id)


@router.patch("/{webhook_id}", response_model=WebhookEndpointPublic)
async def update_webhook(webhook_id: str, in_: WebhookUpdate, session: SessionDep, current_user: CurrentUser):
    ep = await crud_wh.get_endpoint(session, id=webhook_id)
    if not ep or ep.user_id != current_user.id:
        raise HTTPException(404)
    return await crud_wh.update_endpoint(session, ep=ep, in_=in_)


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str, session: SessionDep, current_user: CurrentUser):
    ep = await crud_wh.get_endpoint(session, id=webhook_id)
    if not ep or ep.user_id != current_user.id:
        raise HTTPException(404)
    await crud_wh.delete_endpoint(session, ep=ep)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryPublic])
async def list_deliveries(webhook_id: str, session: SessionDep, current_user: CurrentUser):
    ep = await crud_wh.get_endpoint(session, id=webhook_id)
    if not ep or ep.user_id != current_user.id:
        raise HTTPException(404)
    return await crud_wh.list_deliveries_for_endpoint(session, endpoint_id=webhook_id)
```

### 4.7 Migration
```python
# alembic/versions/0015_add_webhook_sender.py
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"


def upgrade() -> None:
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
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active','disabled','suspended')", name="ck_webhook_endpoints_status"),
        sa.CheckConstraint("url ~ '^https?://.+'", name="ck_webhook_endpoints_url_format"),
    )
    op.create_index("ix_webhook_endpoints_user_id", "webhook_endpoints", ["user_id"])

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("endpoint_id", sa.Uuid(), sa.ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(127), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempt_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.String(4096), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending','succeeded','failed','dead')", name="ck_webhook_deliveries_status"),
    )
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_event_id", "webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_endpoints_user_id", "webhook_endpoints")
    op.drop_table("webhook_endpoints")
```

---

### 4.10 HMAC signature helper with timing-safe verify
```python
# app/webhooks/signature.py
"""Compute and verify HMAC-SHA256 signatures for webhook payloads.

Every outbound delivery attaches an `X-Signature: t=<ts>,v1=<hex>` header
where the MAC is computed over `f"{ts}.{body}"`. Receivers verify using
the exact same construction, reject signatures older than 5 minutes to
mitigate replay, and use a constant-time comparison so a remote attacker
cannot deduce valid signatures byte by byte via timing.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

MAX_SIGNATURE_AGE_SECONDS = 300


@dataclass(frozen=True)
class SignatureHeader:
    timestamp: int
    v1_hex: str

    def to_header_value(self) -> str:
        return f"t={self.timestamp},v1={self.v1_hex}"


def sign_payload(secret: str, body: bytes, timestamp: int | None = None) -> SignatureHeader:
    if not secret:
        raise ValueError("secret must be non-empty")
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode("utf-8") + body
    mac = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return SignatureHeader(timestamp=ts, v1_hex=mac)


def parse_signature_header(header_value: str) -> SignatureHeader | None:
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
    """Constant-time verify + replay window check."""
    header = parse_signature_header(header_value)
    if header is None:
        return False
    now_ts = now if now is not None else int(time.time())
    if abs(now_ts - header.timestamp) > MAX_SIGNATURE_AGE_SECONDS:
        return False
    expected = sign_payload(secret, body, header.timestamp)
    return hmac.compare_digest(expected.v1_hex, header.v1_hex)
```



## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Every payload is HMAC-signed** | Worker calls `sign_payload(secret, body, ts)` and sets `X-Signature`. Receivers verify or reject. |
| QS-2 | **Bodies are deterministically serialized** | `json.dumps(payload, separators=(",",":"), sort_keys=True)` ensures byte-stable signatures across re-serializations. |
| QS-3 | **Retries follow a fixed schedule** | `ATTEMPT_DELAYS_SECONDS` constant; total bound ~32h; deterministic and predictable. |
| QS-4 | **Dead-letter after N attempts** | After `max_attempts`, status flips to `dead`; no more retries; visible in admin UI. |
| QS-5 | **Auto-disable on N consecutive failures** | `consecutive_failures` increments per failure; resets on success; threshold disables endpoint. |
| QS-6 | **Reset success counter on success** | `consecutive_failures = 0` on any 2xx response. |
| QS-7 | **Per-endpoint isolation** | A failing endpoint NEVER blocks others; ARQ jobs run concurrently up to `max_jobs`. |
| QS-8 | **HTTP timeout is bounded** | `httpx.AsyncClient(timeout=10)` per attempt; never hangs. |
| QS-9 | **Owner-only management** | Routes verify `endpoint.user_id == current_user.id` for update/delete/list. |
| QS-10 | **Payload size cap** | `send_webhook` raises if body > limit BEFORE creating any DB rows. |
| QS-11 | **All attempts persisted** | Every attempt updates `WebhookDelivery` with status, http_status, response_body, error. |
| QS-12 | **Secret never returned in responses** | `WebhookEndpointPublic` schema excludes `secret`. Returned ONLY at create response. |
| QS-13 | **URL must be http or https** | DB CheckConstraint `^https?://.+`. |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `WebhookEndpoint` and `WebhookDelivery` models exist | File `app/models/webhook.py` |
| CC-02 | `app/core/webhooks/signer.py` with `sign_payload` + `verify_signature` | File exists |
| CC-03 | `app/core/webhooks/backoff.py` with `ATTEMPT_DELAYS_SECONDS` | File exists |
| CC-04 | `app/core/webhooks/sender.py` with `send_webhook` | File exists |
| CC-05 | `app/workers/webhook_worker.py` with `deliver_webhook` ARQ task | File exists |
| CC-06 | `app/crud/webhook.py` with create/list/update/delete | File exists |
| CC-07 | `app/api/routes/webhooks.py` admin routes | File exists |
| CC-08 | `app/schemas/webhook.py` with all schemas | File exists |
| CC-09 | Migration `0015_add_webhook_sender.py` | File exists |
| CC-10 | Migration creates 2 tables + check constraints + indexes | Inspect upgrade() |
| CC-11 | URL CheckConstraint `^https?://.+` | grep |
| CC-12 | Status enums on both tables | grep |
| CC-13 | Settings: `WEBHOOK_MAX_ATTEMPTS`, `WEBHOOK_HTTP_TIMEOUT_SECONDS`, `WEBHOOK_MAX_PAYLOAD_BYTES`, `WEBHOOK_DISABLE_AFTER_FAILURES` | grep |
| CC-14 | Routes registered in `app/api/main.py` | grep |
| CC-15 | OpenAPI exposes endpoints | curl /openapi.json |
| CC-16 | New file `tests/test_webhook_sender.py` with 30 tests | File exists |
| CC-17 | Existing tests pass | pytest 0 failures |
| CC-18 | All files parse | Tool internal |
| CC-19 | Tool execution time < 5s | Time measurement |
| CC-20 | `send_webhook` enqueue latency < 5 ms | Benchmark T-29 |
| CC-21 | Backoff schedule deterministic | T-15 |
| CC-22 | Auto-disable after N failures | T-19 |
| CC-23 | Sign deterministic for same body | T-04 |
| CC-24 | Verify rejects forged signature | T-05 |
| CC-25 | Verify rejects stale timestamp | T-06 |
| CC-26 | Idempotent re-run | T-26 |
| CC-27 | Owner check on update/delete | T-22 |
| CC-28 | Payload size cap enforced | T-13 |
| CC-29 | Secret excluded from list response | T-21 |
| CC-30 | Worker class registered for ARQ | grep WorkerSettings |

---

## 7. Definition of Done (DoD)

- [ ] All 30 Completeness Criteria verified
- [ ] All 13 Quality Standards enforced
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
| INV-WS-01 | A delivery body NEVER differs between retries | Body is generated once at delivery row creation; all attempts reuse same `payload` | T-09 |
| INV-WS-02 | A delivery NEVER exceeds `max_attempts` | Worker checks attempt counter before scheduling next retry | T-15 |
| INV-WS-03 | A signature ALWAYS proves the body has not been tampered with | HMAC-SHA256 over `<ts>.<body>` with shared secret | T-04, T-05 |
| INV-WS-04 | An endpoint with > N consecutive failures is ALWAYS disabled | `_handle_failure` flips status when threshold reached | T-19 |
| INV-WS-05 | A successful delivery resets consecutive_failures to 0 | Worker on 2xx — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-18 |
| INV-WS-06 | A delivery with status `dead` is NEVER retried | Worker checks status before processing — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-23 |
| INV-WS-07 | The endpoint secret is NEVER returned by list/get endpoints | `WebhookEndpointPublic` schema excludes `secret` — enforced by dedicated check in `tests/test_invariants.py` and `app/core/guards.py` on every write path | T-21 |

---

## 9. User Stories

### 9.1 Event emission from app code (US-01 .. US-05)

**US-01: Register a partner endpoint via the admin API**
- **As a** SaaS developer whose customer wants real-time push notifications for `order.paid` events
- **I want** to POST `{"url": "https://hooks.partner.com/orders", "events": ["order.paid"], "description": "partner-prod"}` to `/webhooks/`
- **So that** I get a freshly generated `secret` I can share with the partner and the endpoint appears in my subscription list
- **Given:** the caller is authenticated and `url` passes the `^https?://.+` constraint (CC-11)
- **When:** `POST /webhooks/` is sent with a valid body
- **Then:**
  - HTTP 201 with `WebhookEndpointPublic` body containing `id`, `url`, `events`, `status="active"`, and `secret` (returned only this once, per INV-WS-07 / CC-29 / T-21)
  - A `webhook_endpoints` row exists with `consecutive_failures=0` and `status="active"`

**US-02: Emit an event without blocking the HTTP request path**
- **As a** backend engineer processing an `order.paid` Stripe callback in a FastAPI route handler
- **I want** to call `await send_webhook("order.paid", {"order_id": order.id, "amount": total})` inside the handler
- **So that** the HTTP response returns to Stripe within the SLA while the webhook delivery happens asynchronously in a background ARQ worker
- **Given:** at least one active endpoint is subscribed to `order.paid` and the ARQ Redis pool is reachable
- **When:** `send_webhook("order.paid", payload)` is awaited
- **Then:**
  - The call completes in < 5 ms (CC-20 / T-29)
  - A `webhook_deliveries` row with `status="pending"` exists for each subscribed endpoint
  - An ARQ job `deliver_webhook` has been enqueued in Redis — no HTTP POST to the partner has been made yet from within the route handler

**US-03: Payload size guard fires before any DB writes**
- **As a** platform engineer who wants to prevent oversized payloads from filling the `webhook_deliveries` table
- **I want** `send_webhook` to raise `ValueError("Webhook payload too large")` when the serialized body exceeds `WEBHOOK_MAX_PAYLOAD_BYTES` (256 KB by default)
- **So that** no delivery row is created and no ARQ job is enqueued for a payload that partners could never process anyway
- **Given:** `WEBHOOK_MAX_PAYLOAD_BYTES = 262144` and one active endpoint subscribed to `item.exported`
- **When:** `await send_webhook("item.exported", giant_dict)` is called with a 300 KB payload
- **Then:**
  - `ValueError` is raised with message `"Webhook payload too large"` (CC-28 / T-13)
  - Zero `webhook_deliveries` rows are created
  - Zero ARQ jobs are enqueued
  - The calling route returns an appropriate 4xx to its own caller

**US-04: Fan-out delivers to all subscribed endpoints independently**
- **As a** marketplace operator with three partners (payments, analytics, fulfillment) each registered for `item.created`
- **I want** a single `await send_webhook("item.created", payload)` to enqueue one delivery per partner
- **So that** a transient failure at the analytics webhook never delays or blocks delivery to the fulfillment endpoint
- **Given:** three `webhook_endpoints` rows with `status="active"` and `events` containing `"item.created"`
- **When:** `send_webhook("item.created", {"item_id": "abc"})` is called
- **Then:**
  - Three `webhook_deliveries` rows are created, each with a distinct `endpoint_id` and the same `event_id` UUID (INV-WS-01)
  - Three ARQ jobs are enqueued independently — worker failures on one job do not affect the others (QS-7)

**US-05: Events not subscribed to are silently ignored**
- **As a** product manager who configured the payments partner to receive only `payment.refunded` events
- **I want** `order.paid` to never reach the payments endpoint
- **So that** partners are not flooded with events they did not opt into
- **Given:** one endpoint with `events=["payment.refunded"]` and no endpoint subscribed to `order.paid`
- **When:** `await send_webhook("order.paid", payload)` is called
- **Then:**
  - The call returns `0` (zero deliveries enqueued)
  - No `webhook_deliveries` rows are created
  - No ARQ jobs are enqueued for this event

---

### 9.2 HMAC signature generation (US-06 .. US-10)

**US-06: Every outbound delivery carries a Stripe-style X-Signature header**
- **As a** security-conscious partner developer whose intake server validates every incoming webhook
- **I want** every POST from the sender to include `X-Signature: t=<unix_seconds>,v1=<sha256_hex>`
- **So that** my server can prove the body was not modified in transit and reject replays older than 5 minutes
- **Given:** an active endpoint with a known `secret` and a pending delivery
- **When:** the ARQ worker dispatches the delivery
- **Then:**
  - The `X-Signature` header is present and matches the format `t=\d+,v1=[0-9a-f]{64}` (CC-02 / INV-WS-03)
  - `verify_signature(secret, body_bytes, header_value)` returns `True` (T-07)
  - The `t=` value is within 5 seconds of the actual dispatch time

**US-07: Deterministic JSON serialization makes the signature byte-stable**
- **As a** platform engineer who may refactor the payload construction code in a future sprint
- **I want** the serialized body to always be `json.dumps(payload, separators=(",",":"), sort_keys=True).encode("utf-8")` regardless of dict insertion order
- **So that** the HMAC is identical even if the upstream code changes key ordering, and re-verification of stored bodies always passes
- **Given:** `payload = {"z": 1, "a": 2}` delivered twice with different Python dict orderings
- **When:** `sign_payload(secret, body)` is called with each serialization
- **Then:**
  - Both calls produce `body_bytes = b'{"a":2,"z":1}'` (sort_keys=True, compact separators)
  - Both `v1=` hex values are identical (CC-23 / INV-WS-03 / T-04)

**US-08: Body tampering is detected by the receiver**
- **As a** security engineer writing a receiver integration test
- **I want** `verify_signature` to return `False` when any byte of the request body is changed after signing
- **So that** man-in-the-middle tampering is caught before the event is processed
- **Given:** a valid `(secret, body_bytes, header_value)` triple where the signature was computed correctly
- **When:** `body_bytes` is mutated (e.g., one character changed) and `verify_signature(secret, mutated_body, header_value)` is called
- **Then:**
  - Returns `False` (T-05 / INV-WS-03)
  - The comparison uses `hmac.compare_digest` to avoid timing side-channels (QS-1)

**US-09: Stale signatures are rejected to mitigate replay attacks**
- **As a** security engineer protecting the partner endpoint from replay attacks where an attacker re-sends a captured valid webhook
- **I want** `verify_signature` to reject signatures whose `t=` timestamp is more than 300 seconds old
- **So that** a valid-but-old signed payload cannot be replayed by an adversary who captured the request
- **Given:** a valid signature where `t=<unix_ts>` and `now - t = 601` seconds (beyond the 300-second tolerance)
- **When:** `verify_signature(secret, body_bytes, header_value, now=now)` is called
- **Then:**
  - Returns `False` (T-06 / CC-25)
  - A fresh duplicate of the same body signed with `t=now` would return `True`, proving the body itself is valid but the timestamp is too old

**US-10: X-Event-Id header enables idempotent receiver processing**
- **As a** partner developer whose order-fulfillment service must be idempotent under retries
- **I want** every delivery attempt for the same logical event to carry the same `X-Event-Id: <uuid>` header
- **So that** my receiver can store the event ID and skip duplicate processing when the sender retries after a 500 error
- **Given:** a delivery with `event_id=uuid4()` that fails on attempt 1 and is retried on attempt 2
- **When:** both HTTP POSTs arrive at the partner endpoint
- **Then:**
  - Both requests have identical `X-Event-Id` values (INV-WS-01 — payload and event_id are never mutated across retries)
  - `X-Attempt: 1` and `X-Attempt: 2` respectively, allowing the receiver to detect retries
  - `X-Event-Type: order.paid` is present on both

---

### 9.3 Retry & backoff (US-11 .. US-15)

**US-11: Transient 5xx from partner triggers exponential retry**
- **As a** platform engineer whose partner webhook endpoint occasionally returns 503 during deploys
- **I want** a failed delivery to be re-enqueued with a 1-second delay after the first failure, then 5s, 30s, 5m, 1h, 6h, 24h
- **So that** a 30-minute partner outage self-heals without any operator intervention
- **Given:** a delivery on attempt 1 that receives HTTP 503
- **When:** `_handle_failure` runs and the worker commits the result
- **Then:**
  - `delivery.status` remains `"pending"` and `delivery.attempt_number = 1`
  - An ARQ job is enqueued with `_defer_by=1` (delay_for_attempt(2) = 1s from `ATTEMPT_DELAYS_SECONDS`)
  - `endpoint.consecutive_failures` increments to 1 (CC-22 / INV-WS-02 / T-10)

**US-12: Network-layer errors (ConnectError, TimeoutException) are retried identically to HTTP errors**
- **As a** DevOps engineer whose partner endpoint has intermittent DNS failures
- **I want** `httpx.ConnectError` and `httpx.TimeoutException` to be caught and treated as retryable failures, not fatal crashes
- **So that** a 10-second network blip does not permanently lose a delivery that would succeed 15 seconds later
- **Given:** the partner endpoint is unreachable (`httpx.ConnectError`) on attempt 1
- **When:** the worker catches the exception in `except (httpx.RequestError, httpx.TimeoutException)`
- **Then:**
  - `delivery.error` is set to `repr(exc)[:500]` (CC-11 / T-11 / T-12)
  - `delivery.status = "pending"`, retry is enqueued
  - No unhandled exception propagates to the ARQ worker — the job completes normally so ARQ does not apply its own retry logic

**US-13: After 7 consecutive failures the delivery reaches dead state**
- **As a** support engineer diagnosing why a customer's integration stopped receiving events
- **I want** a delivery to flip to `status="dead"` after attempt 7 fails, with no further enqueues
- **So that** zombie retries do not consume worker capacity for an integration that has been broken for 32+ hours
- **Given:** a delivery that has failed attempts 1 through 6 and is now on attempt 7 (the final attempt per `WEBHOOK_MAX_ATTEMPTS=7`)
- **When:** attempt 7 receives HTTP 500
- **Then:**
  - `delivery.status = "dead"` (INV-WS-02 / INV-WS-06 / CC-21 / T-14)
  - No further ARQ job is enqueued (`delay_for_attempt(8) = -1`)
  - The attempt is recorded in `webhook_deliveries` with `attempt_number=7`, `http_status=500`, `error="HTTP 500"`

**US-14: Dead deliveries are never re-processed by the worker**
- **As a** platform engineer worried about accidental double-delivery after a manual data fix sets a delivery back to a non-pending state
- **I want** the worker to exit immediately if `delivery.status != "pending"` when it loads the row
- **So that** a race condition or manual DB edit cannot cause a delivery to be processed twice
- **Given:** a `webhook_deliveries` row with `status="dead"` (or `"succeeded"`)
- **When:** `deliver_webhook(ctx, str(delivery.id))` is invoked by the ARQ worker
- **Then:**
  - The worker returns immediately without sending any HTTP request (INV-WS-06 / T-23)
  - No further ARQ enqueue occurs
  - The `delivery.status` column is not modified

**US-15: Backoff delays exactly match the canonical schedule**
- **As a** reliability engineer writing a capacity-planning model for the ARQ worker fleet
- **I want** the retry delays to be deterministic and bounded by `ATTEMPT_DELAYS_SECONDS = [0, 1, 5, 30, 300, 3600, 21600]`
- **So that** I can predict the maximum backlog growth during a prolonged partner outage and provision workers accordingly
- **Given:** a delivery that fails on every attempt from 1 to 7
- **When:** the ARQ enqueue calls are captured (mocking `ctx["redis"].enqueue_job`)
- **Then:**
  - Attempt 2 is enqueued with `_defer_by=1`
  - Attempt 3 with `_defer_by=5`, attempt 4 with `_defer_by=30`, attempt 5 with `_defer_by=300`, attempt 6 with `_defer_by=3600`, attempt 7 with `_defer_by=21600` (CC-21 / T-15)
  - No 8th enqueue occurs (`delay_for_attempt(8) == -1`)

---

### 9.4 Auto-disable & consecutive-failure tracking (US-16 .. US-20)

**US-16: Consecutive failure counter increments on every non-2xx or network error**
- **As a** platform engineer who wants an accurate signal for how unhealthy a partner endpoint is
- **I want** `endpoint.consecutive_failures` to increment by 1 on every delivery failure, regardless of whether the failure was a 4xx, 5xx, or network exception
- **So that** the auto-disable threshold is based on uninterrupted failures, not total failures
- **Given:** an endpoint with `consecutive_failures=3` and a delivery that receives HTTP 404
- **When:** `_handle_failure(delivery, endpoint, error="HTTP 404")` runs
- **Then:**
  - `endpoint.consecutive_failures = 4` (T-16 / INV-WS-04)
  - `endpoint.last_failure_at` is updated to `datetime.now(timezone.utc)`
  - `endpoint.status` remains `"active"` (not yet at threshold)

**US-17: A successful 2xx delivery resets the consecutive failure counter to zero**
- **As a** platform engineer whose partner endpoint recovered after a 4-hour outage
- **I want** the first successful delivery after recovery to reset `consecutive_failures` to 0
- **So that** the auto-disable timer resets cleanly and the partner does not get disabled on the next failure despite having recovered
- **Given:** an endpoint with `consecutive_failures=9` (below the 12-failure threshold)
- **When:** a delivery receives HTTP 200
- **Then:**
  - `endpoint.consecutive_failures = 0` (INV-WS-05 / T-17 / T-18)
  - `endpoint.last_success_at` is updated
  - `delivery.status = "succeeded"` and `delivery.delivered_at` is set

**US-18: After 12 consecutive failures the endpoint is automatically disabled**
- **As a** platform operator who wants the system to protect itself from spending worker cycles on provably dead integrations
- **I want** an endpoint to flip to `status="disabled"` the moment `consecutive_failures` reaches `WEBHOOK_DISABLE_AFTER_FAILURES=12`
- **So that** future events do not create new deliveries for it and worker capacity is not wasted
- **Given:** an endpoint with `consecutive_failures=11` and a delivery currently being processed
- **When:** that delivery fails (any reason)
- **Then:**
  - `endpoint.consecutive_failures = 12`
  - `endpoint.status = "disabled"` (INV-WS-04 / CC-22 / T-19)
  - `delivery.status = "dead"` (the in-flight delivery is also killed)
  - Subsequent calls to `send_webhook` for any event return 0 deliveries for this endpoint (T-20)

**US-19: Operator can re-enable a disabled endpoint via PATCH**
- **As a** customer success engineer who confirmed the partner fixed their webhook receiver
- **I want** to PATCH `{"status": "active"}` on the disabled endpoint to re-enable it
- **So that** future events resume delivery without any code changes or worker restarts
- **Given:** an endpoint with `status="disabled"`
- **When:** the owning user PATCHes `/webhooks/{id}` with `{"status": "active"}`
- **Then:**
  - `endpoint.status = "active"` (T-22)
  - The next `send_webhook` call for a subscribed event creates a new delivery row and enqueues an ARQ job
  - `consecutive_failures` is NOT automatically reset to 0 by the re-enable — the operator should also reset it explicitly to avoid an immediate re-disable on the first failure

**US-20: Disabled endpoint is skipped during fan-out without error**
- **As a** platform engineer who wants `send_webhook` to remain non-blocking even when some endpoints are disabled
- **I want** `list_endpoints_for_event` to return only `status="active"` endpoints
- **So that** a disabled partner does not cause a delivery row or ARQ job, keeping the queue clean
- **Given:** two endpoints subscribed to `payment.refunded`; one is `"active"` and one is `"disabled"`
- **When:** `await send_webhook("payment.refunded", payload)` is called
- **Then:**
  - Only 1 delivery row is created (for the active endpoint)
  - `send_webhook` returns `1`
  - No delivery row is created for the disabled endpoint (CC-22 / INV-WS-04)

---

### 9.5 Audit & observability (US-21 .. US-25)

**US-21: Every delivery attempt is persisted in webhook_deliveries for support debugging**
- **As a** customer support engineer investigating a customer ticket "I never received the order.paid webhook from 3 hours ago"
- **I want** to query `webhook_deliveries WHERE event_id = '<uuid>'` and see the full attempt history including HTTP status codes, response bodies, and error messages
- **So that** I can tell the customer exactly what happened: "attempt 1 failed with 503, attempt 2 succeeded at 14:03:27 UTC"
- **Given:** a delivery that failed on attempt 1 (HTTP 503) and succeeded on attempt 2 (HTTP 200)
- **When:** I query `webhook_deliveries` filtered by `event_id`
- **Then:**
  - Two rows exist: `attempt_number=1, status="succeeded"` after the retry path overwrites pending, or separate delivery tracking per the model
  - Each row has `http_status`, `response_body[:4096]`, `error`, and `scheduled_at` populated (CC-16 / QS-11 / T-08)
  - `delivery.delivered_at` is non-null on the succeeded row

**US-22: The endpoint secret is never exposed in list or get responses**
- **As a** security auditor reviewing the webhook API surface
- **I want** `GET /webhooks/` and `GET /webhooks/{id}/deliveries` to never include the `secret` field
- **So that** a compromised session token cannot be used to extract HMAC signing secrets that protect partner integrations
- **Given:** an endpoint whose `secret` was shown only at creation time
- **When:** `GET /webhooks/` is called by the owning user
- **Then:**
  - The response JSON does not contain a `secret` key (INV-WS-07 / CC-29 / T-21)
  - `WebhookEndpointPublic` schema enforces this exclusion at the Pydantic layer, not just at the route layer

**US-23: Cross-user access to webhook management returns 404, not 403**
- **As a** security engineer verifying that user A cannot enumerate or modify user B's webhooks
- **I want** `PATCH /webhooks/{b_id}` by user A to return 404 (not 403) so that the endpoint ID is not confirmed to exist
- **So that** an attacker who guesses a UUID cannot determine whether it belongs to another user or does not exist at all
- **Given:** a `webhook_endpoints` row owned by user B, and user A is authenticated with a valid session
- **When:** user A sends `PATCH /webhooks/{b_id}` with any body
- **Then:**
  - HTTP 404 is returned (CC-27 / T-24 / T-25)
  - The route checks `ep.user_id == current_user.id` before returning the object (QS-9)
  - The same 404 behaviour applies to DELETE and `GET /{id}/deliveries`

**US-24: Delivery list for an endpoint provides a replay starting point for operators**
- **As a** platform engineer who wants to manually trigger a re-delivery after a critical partner outage was resolved
- **I want** `GET /webhooks/{id}/deliveries` to list all delivery records including `dead` ones with their full error context
- **So that** I can identify the `event_id` of failed deliveries and re-enqueue them from a DLQ or admin script
- **Given:** an endpoint with 3 deliveries: 1 `succeeded`, 1 `dead` (exhausted retries), 1 `pending`
- **When:** the owning user calls `GET /webhooks/{id}/deliveries`
- **Then:**
  - All 3 rows are returned as `WebhookDeliveryPublic` objects (CC-07 / QS-11)
  - Each includes `status`, `attempt_number`, `http_status`, `error`, `scheduled_at`, `delivered_at`
  - The `dead` row has `attempt_number=7` and non-null `error`, giving the operator all the information needed to decide whether to replay

**US-25: Tool execution is idempotent — re-running on an already-instrumented project is a no-op**
- **As a** CI engineer whose pipeline runs `fastapi_add_webhook_sender` on every branch
- **I want** re-running the tool on a project that already has all webhook files to produce zero file changes
- **So that** the pipeline is safe to run repeatedly without creating duplicate migrations or overwriting custom changes developers have made
- **Given:** a project where `add_webhook_sender` was already run and all generated files exist unchanged
- **When:** `add_webhook_sender(project_dir)` is invoked again
- **Then:**
  - The tool detects all 11+ expected files already exist with correct content
  - No files are written or modified (T-26)
  - The return dict includes `"idempotent": true` and `"files_created": 0`
  - Existing `alembic/versions/0015_add_webhook_sender.py` is not duplicated or overwritten

## 10. Test Plan

### 10.1 Subscription & dispatch

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Create webhook endpoint | logged in | POST /webhooks/ | 201, secret returned |
| T-02 | List my webhooks | created | GET /webhooks/ | list, no secret |
| T-03 | Send event creates delivery rows | 1 endpoint, send_webhook | inspect | 1 delivery row |
| T-04 | Sign deterministic for same body+ts | sign twice with same ts | compare | identical |
| T-05 | Verify rejects forged signature | tamper body | verify | False |
| T-06 | Verify rejects stale timestamp | ts > tolerance | verify | False |
| T-07 | Verify accepts fresh timestamp | ts within tolerance | verify | True |

### 10.2 Delivery & retries

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-08 | 200 response → succeeded | mock receiver 200 | run worker | status=succeeded |
| T-09 | Body identical across retries | fail then retry | inspect | identical bytes |
| T-10 | 500 response → pending+retry | mock 500 | run worker | enqueued for retry |
| T-11 | Network error → retry | mock ConnectError | run worker | enqueued for retry |
| T-12 | Timeout → retry | mock hang | run worker | enqueued |
| T-13 | Payload too large → ValueError | 300 KB payload | send_webhook | raises |
| T-14 | Worker handles attempt 7 max | fail 7 times | observe | status=dead, no further enqueues |
| T-15 | Backoff schedule | track delays | inspect enqueue calls | matches ATTEMPT_DELAYS |

### 10.3 Auto-disable & lifecycle

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-16 | Failure increments counter | 1 fail | inspect | counter=1 |
| T-17 | Success resets counter | counter=5, then success | inspect | 0 |
| T-18 | Reset on 2xx | counter=11, success | inspect | 0 |
| T-19 | Auto-disable on 12 failures | 12 fails | inspect | endpoint.status=disabled |
| T-20 | Disabled endpoint not enqueued | disabled | send_webhook | 0 deliveries |
| T-21 | Secret excluded from list | GET /webhooks/ | inspect | no secret |
| T-22 | Owner can re-enable | PATCH status=active | inspect | active |
| T-23 | Dead delivery not retried | status=dead | worker | skipped |

### 10.4 Owner & schemas

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-24 | Cross-user GET → 404 | userB tries userA | request | 404 |
| T-25 | Cross-user PATCH → 404 | userB tries userA | request | 404 |
| T-26 | Tool re-run no-op | installed | run | no changes |
| T-27 | URL must be http(s) | url=ftp:// | POST | 422 |
| T-28 | OpenAPI exposes routes | installed | curl /openapi.json | present |

### 10.5 Performance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-29 | Enqueue p99 < 5 ms | benchmark send_webhook | measure | < 5 ms |
| T-30 | Worker throughput ≥ 100/sec | mock receiver | run 1000 deliveries | < 10s wall |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|---------------|-------------|-------|
| `add_outbox_pattern` | **Outbox first** | ✅ Compatible | Outbox can dispatch via `send_webhook` after commit, ensuring at-least-once delivery. |
| `add_audit_log` | **Audit first** | ✅ Compatible | Webhook events recorded as part of audit trail for the user. |
| `add_multi_tenancy` | **Tenancy first** | ⚠️ Caveat | Webhooks scoped to user; user is in tenant. Add `tenant_id` to webhook_endpoints if you want explicit cross-tenant isolation. |
| `add_rbac` | No | ⚠️ Caveat | Decide whether webhook management is a separate permission. |
| `add_circuit_breaker` | No | ⚠️ Caveat | Add a per-endpoint breaker if a single bad receiver should not consume the worker pool. |
| `add_rate_limit` | No | ⚠️ Caveat | Optional: rate-limit per-endpoint to avoid overwhelming the receiver. |
| `add_feature_flags` | No | ✅ Compatible | Can flag-gate the webhook feature. |
| `add_oauth2_provider` | No | ✅ Compatible | Independent. |
| `add_long_running_task` | No | ✅ Compatible | Long-running tasks can publish progress as webhooks. |
| `add_sse` | No | ✅ Compatible | Same publisher pattern; both can be triggered for the same event. |
| TOOL-034 performance_baseline | downstream | `send_webhook` enqueue latency and `POST /webhooks/`, `GET /webhooks/{id}/deliveries` route latencies are captured in the baseline (target enqueue p99 < 5 ms, route p99 < 80 ms); a change to `app/workers/webhook_worker.py` `deliver_webhook` that adds a synchronous retry loop will be caught before merge |
| TOOL-051 fastapi_doctor | downstream | doctor detects `add_webhook_sender` is installed but no `add_outbox_pattern` is present and recommends TOOL-022 `add_outbox_pattern` to guarantee at-least-once delivery — if `send_webhook` is called before the originating DB transaction commits, events can be lost on crash |
| TOOL-029 security_scan | downstream | `app/core/webhooks/signer.py` `sign_payload` and `verify_signature` are scanned for timing-attack patterns (must use `hmac.compare_digest` not `==`), and `app/api/routes/webhooks.py` is scanned for missing ownership checks on PATCH/DELETE; any CRITICAL finding blocks merge |

**Conflicts:**
- None identified.

---

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout HEAD~1 -- app/models/webhook.py app/core/webhooks app/workers/webhook_worker.py \
  app/crud/webhook.py app/api/routes/webhooks.py app/schemas/webhook.py app/api/main.py app/core/config.py
rm alembic/versions/*_add_webhook_sender.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops `webhook_deliveries` and `webhook_endpoints`.

### Failure mode: tool partially modified files
- `git checkout -- {files}` to revert
- `rm alembic/versions/*_add_webhook_sender.py`
- Drop partially-created tables
- Re-run

### Emergency: a webhook is being abused or misdelivers
1. PATCH endpoint to status=`suspended`
2. Inspect `webhook_deliveries` for that endpoint
3. If secret leaked: rotate via PATCH (regenerate); old deliveries already sent stay tied to old secret; future deliveries use new secret


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

### Failure mode: HMAC signing key leaked or ARQ delivery queue stuck
```bash
# ── Step 1: Detect if signing key was exposed ──────────────────────────────
# Search logs for any accidental key emission (should return 0 lines)
grep -r "WEBHOOK_SIGNING_SECRET" /var/log/app/ | grep -v "redacted"

# ── Step 2: Rotate the signing secret immediately ──────────────────────────
# Generate a new secret and update your secrets manager / env
NEW_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# Update in vault / k8s secret:
kubectl create secret generic webhook-signing \
  --from-literal=WEBHOOK_SIGNING_SECRET="$NEW_SECRET" \
  --dry-run=client -o yaml | kubectl apply -f -
# Force pod rollout to pick up new secret
kubectl rollout restart deployment/api

# ── Step 3: Mark in-flight deliveries tied to OLD secret as tainted ────────
# Deliveries sent with the old key are already delivered; receivers must
# re-verify or treat as unverified. Flag them in the DB:
psql "$DATABASE_URL" -c "
  UPDATE webhook_deliveries
  SET status = 'key_rotated_unverified'
  WHERE status IN ('pending','failed')
    AND created_at < NOW();
"

# ── Step 4: If ARQ delivery queue is stuck (jobs visible but not running) ──
# Check ARQ queue depth in Redis
redis-cli -u "$REDIS_URL" LLEN arq:queue:default

# Inspect stuck jobs (top 10)
redis-cli -u "$REDIS_URL" LRANGE arq:queue:default 0 9

# Restart the ARQ worker pod to clear any deadlock
kubectl rollout restart deployment/arq-worker

# Wait for worker to come back up, then verify queue drains
kubectl rollout status deployment/arq-worker --timeout=120s
redis-cli -u "$REDIS_URL" LLEN arq:queue:default   # should decrease

# ── Step 5: Check dead-letter table for endpoints auto-disabled ────────────
psql "$DATABASE_URL" -c "
  SELECT id, url, failure_count, status, updated_at
  FROM webhook_endpoints
  WHERE status = 'disabled'
  ORDER BY updated_at DESC
  LIMIT 20;
"
# Re-enable an endpoint once the receiver is healthy:
# PATCH /webhooks/endpoints/{id}  body: {"status": "active"}
```

### Emergency: dead-letter table growing / ARQ dependency outage
```bash
# ── Step 1: Confirm ARQ/Redis health ───────────────────────────────────────
redis-cli -u "$REDIS_URL" PING            # should return PONG
redis-cli -u "$REDIS_URL" INFO server | grep redis_version

# ── Step 2: Pause new enqueuing to stop DLQ growth ─────────────────────────
# Set env var WEBHOOK_DELIVERY_ENABLED=false and redeploy so send_webhook()
# returns early without enqueuing; existing rows are preserved
kubectl set env deployment/api WEBHOOK_DELIVERY_ENABLED=false
kubectl rollout status deployment/api --timeout=90s

# ── Step 3: Inspect the dead-letter table ──────────────────────────────────
psql "$DATABASE_URL" -c "
  SELECT endpoint_id, COUNT(*) AS dlq_count,
         MIN(next_attempt_at) AS oldest_pending,
         MAX(attempt_count)   AS max_attempts
  FROM webhook_deliveries
  WHERE status = 'failed'
  GROUP BY endpoint_id
  ORDER BY dlq_count DESC
  LIMIT 20;
"

# ── Step 4: Bulk-expire truly dead deliveries (> 7 days) ───────────────────
psql "$DATABASE_URL" -c "
  UPDATE webhook_deliveries
  SET status = 'expired'
  WHERE status = 'failed'
    AND created_at < NOW() - INTERVAL '7 days';
"

# ── Step 5: Re-enable once Redis is healthy ────────────────────────────────
kubectl set env deployment/api WEBHOOK_DELIVERY_ENABLED=true
kubectl rollout status deployment/api --timeout=90s

# ── Step 6: Replay retained failed deliveries (manual trigger) ────────────
# Reset status to 'pending' so the worker picks them up again
psql "$DATABASE_URL" -c "
  UPDATE webhook_deliveries
  SET status = 'pending', next_attempt_at = NOW(), attempt_count = 0
  WHERE status = 'failed'
    AND created_at >= NOW() - INTERVAL '7 days';
"
# Verify the ARQ worker begins draining
redis-cli -u "$REDIS_URL" LLEN arq:queue:default   # should grow then shrink
```


---

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | Project has no Redis or ARQ | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-2 | Project has no User model | Tool errors; the operation returns a structured error response and no side effects persist |
| EC-3 | URL changes mid-retry | Worker uses CURRENT endpoint URL on each attempt; intentional |
| EC-4 | Endpoint deleted while delivery pending | Delivery row CASCADE-deleted; worker no-op |
| EC-5 | Worker crashes mid-attempt | Job retried by ARQ; idempotency handled by attempt counter |
| EC-6 | Receiver returns 200 + slow body | Worker reads body up to 4096 chars; truncates |
| EC-7 | Receiver returns 200 but takes > 10s to respond | Timeout fires; counted as failure |
| EC-8 | Receiver returns 200 + huge body | Truncated to 4096 chars in `response_body` |
| EC-9 | Endpoint with 0 events subscribed | send_webhook never enqueues for it |
| EC-10 | DNS resolution fails | httpx.RequestError; retry; the operation returns a structured error response and no side effects persist |
| EC-11 | TLS certificate invalid | httpx raises; retry; consider configurable verify=False (NOT recommended) |
| EC-12 | Receiver redirects (3xx) | httpx follows redirects up to 20; final status counts |
| EC-13 | Receiver requires custom headers | Not supported by default; future enhancement |
| EC-14 | User deletes endpoint while worker has job in flight | Worker checks endpoint status; if disabled or missing, marks delivery dead |
| EC-15 | ARQ Redis down | send_webhook fails with RedisError; caller decides |

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
10. ✅ One human dev configures a webhook against `httpbin.org/post`, triggers an event, sees a delivery row succeed, and verifies the X-Signature header on the receiver

---

## 15. Implementation Checklist

### 15.1 Pre-flight checks
- [ ] Validate `project_dir` exists
- [ ] Validate User model exists
- [ ] Validate Redis configured
- [ ] Validate ARQ installed
- [ ] Detect existing tables → idempotent skip if found
- [ ] Assert pre-flight raises `MissingDependencyError` when ARQ is not installed via `test_preflight.py::test_missing_arq_raises`
- [ ] Assert pre-flight returns `{"skipped": true}` when `webhook_endpoints` table already exists via `test_preflight.py::test_idempotent_skip_when_table_exists`

### 15.2 Settings
- [ ] Add `WEBHOOK_MAX_ATTEMPTS: int = 7`
- [ ] Add `WEBHOOK_HTTP_TIMEOUT_SECONDS: float = 10.0`
- [ ] Add `WEBHOOK_MAX_PAYLOAD_BYTES: int = 262_144`
- [ ] Add `WEBHOOK_DISABLE_AFTER_FAILURES: int = 12`
- [ ] Assert `WEBHOOK_MAX_ATTEMPTS` env override is honoured by the ARQ worker retry loop via `test_settings.py::test_webhook_max_attempts_env_override`
- [ ] Assert `WEBHOOK_DISABLE_AFTER_FAILURES` disables the endpoint after the configured number of consecutive failures via `test_settings.py::test_webhook_disable_after_failures_threshold`
- [ ] Run `mypy --strict app/core/config.py` — zero new errors after adding the four fields

### 15.3 Models
- [ ] Create `app/models/webhook.py`
- [ ] CheckConstraints on status + url format
- [ ] Verify file parses
- [ ] Assert `CheckConstraint` on `status` rejects values outside `{active, disabled, paused}` via `test_models_webhook.py::test_invalid_status_rejected_by_check_constraint`
- [ ] Assert `CheckConstraint` on `url` rejects non-HTTPS values via `test_models_webhook.py::test_non_https_url_rejected_by_check_constraint`
- [ ] Run `ruff check app/models/webhook.py` and `mypy app/models/webhook.py` — zero findings

### 15.4 Signer & backoff
- [ ] Create `app/core/webhooks/signer.py`
- [ ] Create `app/core/webhooks/backoff.py`
- [ ] Verify files parse
- [ ] Confirm HMAC-SHA256 signature is bytes-stable (deterministic JSON serialisation) via `test_signature.py::test_deterministic_json`
- [ ] Assert `sign(payload, secret_a) != sign(payload, secret_b)` for two different secrets via `test_signature.py::test_different_secrets_produce_different_signatures`
- [ ] Assert backoff delays follow exponential schedule: attempt 1→2s, 2→4s, 3→8s via `test_backoff.py::test_exponential_delay_schedule`
- [ ] Run `mypy --strict app/core/webhooks/signer.py app/core/webhooks/backoff.py` — zero errors

### 15.5 Sender public API
- [ ] Create `app/core/webhooks/sender.py`
- [ ] Implement `send_webhook` with payload size check
- [ ] Verify file parses
- [ ] Assert `send_webhook` raises `PayloadTooLargeError` when payload exceeds `WEBHOOK_MAX_PAYLOAD_BYTES` via `test_sender.py::test_send_raises_on_oversized_payload`
- [ ] Assert `send_webhook` enqueues an ARQ job and returns a delivery ID via `test_sender.py::test_send_returns_delivery_id`
- [ ] Run `ruff check app/core/webhooks/sender.py` — zero findings

### 15.6 Worker
- [ ] Create `app/workers/webhook_worker.py`
- [ ] Implement `deliver_webhook` ARQ task
- [ ] Define `WorkerSettings` class
- [ ] Verify file parses
- [ ] Assert `deliver_webhook` records `HTTP 2xx` as `delivered` in the `webhook_deliveries` table via `test_worker.py::test_deliver_records_success_on_2xx`
- [ ] Assert `deliver_webhook` increments failure count and re-enqueues with backoff on non-2xx via `test_worker.py::test_deliver_requeues_on_non_2xx`
- [ ] Assert endpoint is set to `disabled` after `WEBHOOK_DISABLE_AFTER_FAILURES` consecutive failures via `test_worker.py::test_endpoint_disabled_after_max_failures`

### 15.7 CRUD
- [ ] Create `app/crud/webhook.py` with create_endpoint, list_endpoints_for_user, list_endpoints_for_event, get_endpoint, update_endpoint, delete_endpoint, create_delivery, get_delivery, list_deliveries_for_endpoint
- [ ] Verify file parses
- [ ] Assert `create_endpoint` returns the generated secret exactly once via `test_crud_webhook.py::test_create_endpoint_secret_visible_only_on_creation`
- [ ] Assert `list_endpoints_for_event` returns only endpoints subscribed to the given event type via `test_crud_webhook.py::test_list_endpoints_filtered_by_event_type`
- [ ] Add trace span `webhook.crud.create_delivery` with tags `endpoint_id` and `attempt` for observability

### 15.8 Schemas
- [ ] Create `app/schemas/webhook.py`
- [ ] WebhookCreate (url + events + description)
- [ ] WebhookEndpointPublic (no secret)
- [ ] WebhookEndpointCreatedResponse (with secret, shown ONCE)
- [ ] WebhookUpdate (description, events, status)
- [ ] WebhookDeliveryPublic
- [ ] Verify file parses
- [ ] Assert `WebhookEndpointPublic` does not expose the `secret` field via `test_schemas_webhook.py::test_endpoint_public_schema_excludes_secret`
- [ ] Assert `WebhookCreate` validator rejects a non-HTTPS `url` via `test_schemas_webhook.py::test_webhook_create_rejects_non_https_url`
- [ ] Run `mypy --strict app/schemas/webhook.py` — zero errors

### 15.9 Routes
- [ ] Create `app/api/routes/webhooks.py`
- [ ] All endpoints require CurrentUser
- [ ] Owner check on update/delete
- [ ] Add to `app/api/main.py` router include
- [ ] Verify file parses
- [ ] Assert `DELETE /webhooks/{id}` by a non-owner returns 403 via `test_routes_webhooks.py::test_delete_endpoint_by_non_owner_returns_403`
- [ ] Assert `POST /webhooks` response body contains the plaintext `secret` field and it is absent from subsequent `GET /webhooks/{id}` via `test_routes_webhooks.py::test_secret_shown_once_on_create`

### 15.10 Migration
- [ ] Generate `0NNN_add_webhook_sender.py`
- [ ] `upgrade()` creates 2 tables + indexes + check constraints
- [ ] `downgrade()` drops in reverse
- [ ] Verify migration parses
- [ ] Assert `alembic upgrade head` + `alembic downgrade -1` completes cleanly on a blank schema via `test_migrations.py::test_webhook_sender_migration_roundtrip`
- [ ] Assert the `CheckConstraint` on `status` is present in the upgraded schema via `test_migrations.py::test_status_check_constraint_exists_after_upgrade`
- [ ] Run `ruff check alembic/versions/0NNN_add_webhook_sender.py` — zero findings

### 15.11 Test generation
- [ ] Create `tests/test_webhook_sender.py` with all 30 tests
- [ ] Use `respx` to mock httpx receiver
- [ ] Use a worker test harness to invoke `deliver_webhook` directly
- [ ] Verify file parses
- [ ] Assert overall line coverage for `app/core/webhooks/` is ≥ 90% via `pytest --cov=app.core.webhooks --cov-fail-under=90`
- [ ] Assert `test_webhook_sender.py::test_signature_header_present_on_delivery` verifies `X-Webhook-Signature` header is set correctly
- [ ] Run `ruff check tests/test_webhook_sender.py` — zero findings

### 15.12 Atomicity
- [ ] All file writes use temp-file + rename
- [ ] If ANY step fails, rollback all writes
- [ ] Drop partially-created tables on failure
- [ ] Assert mid-run failure leaves no partial files on disk via `test_atomicity.py::test_rollback_removes_partial_files`
- [ ] Assert returned dict lists every rolled-back file path via `test_atomicity.py::test_error_response_lists_rolled_back_files`
- [ ] Run `mypy app/core/webhooks/` — zero errors after rollback path changes

### 15.13 Documentation
- [ ] Append webhook sender section to `core/KNOWLEDGE.md`
- [ ] Add tool entry to `manifest.yaml`
- [ ] Add tool to `SKILL.md` tools table
- [ ] Update `mcp_server.py`
- [ ] Assert `manifest.yaml` entry for `add_webhook_sender` contains `inputs`, `outputs`, and `idempotent: true` fields via `test_manifest.py::test_webhook_sender_tool_manifest_schema`
- [ ] Assert `SKILL.md` tools table row for TOOL-015 links to this spec file via `test_skill_md.py::test_tool_015_row_exists_with_spec_link`
- [ ] Run `ruff check mcp_server.py` — zero new findings after the update

### 15.14 Verification
- [ ] Run `ast.parse` on every modified file
- [ ] Run import audit
- [ ] Run `pytest tests/`
- [ ] Run analyzer
- [ ] Measure tool execution time
- [ ] Measure enqueue p99 latency
- [ ] Assert enqueue p99 latency is < 20 ms measured via `test_webhook_perf.py::test_enqueue_p99_under_20ms`

---

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/webhook.py",
    "app/core/webhooks/__init__.py",
    "app/core/webhooks/signer.py",
    "app/core/webhooks/backoff.py",
    "app/core/webhooks/sender.py",
    "app/workers/webhook_worker.py",
    "app/crud/webhook.py",
    "app/schemas/webhook.py",
    "app/api/routes/webhooks.py",
    "alembic/versions/0015_add_webhook_sender.py",
    "tests/test_webhook_sender.py"
  ],
  "files_modified": [
    "app/api/main.py",
    "app/core/config.py"
  ],
  "metrics": {
    "execution_time_ms": 4123,
    "files_changed": 13,
    "lines_added": 1187,
    "lines_removed": 2,
    "max_attempts": 7,
    "http_timeout_seconds": 10.0,
    "max_payload_bytes": 262144,
    "disable_after_consecutive_failures": 12
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_webhook_sender.py -v",
    "Start the ARQ worker: `arq app.workers.webhook_worker.WorkerSettings`",
    "Subscribe to events: POST /webhooks/ {url:'https://your.endpoint/hook', events:['item.created']}",
    "Trigger an event: from app code call `await send_webhook('item.created', {...})`",
    "Verify the receiver checks `X-Signature` using sign_payload from app/core/webhooks/signer.py"
  ],
  "warnings": [
    "Endpoint secret is shown ONLY at creation time. Save it on the receiver before responding.",
    "Webhook delivery is at-least-once. Receivers MUST be idempotent (use X-Event-Id for dedupe).",
    "ARQ worker must be running for deliveries to fire. In dev, run `arq app.workers.webhook_worker.WorkerSettings`."
  ],
  "notes": [
    "Webhook sender installed with 7 attempts, 10s HTTP timeout, 256KB payload cap, auto-disable after 12 failures.",
    "Two new tables: webhook_endpoints, webhook_deliveries.",
    "Stripe-style signature header: `X-Signature: t=<ts>,v1=<hmac>`.",
    "Backoff: 0s, 1s, 5s, 30s, 300s, 3600s, 21600s (~32h total).",
    "Existing tests still pass: 64/64."
  ]
}
```
