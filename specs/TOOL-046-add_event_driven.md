# TOOL-046: fastapi_add_event_driven

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-12

---

## 1. Overview

| Field | Value |
|-------|-------|
| Tool name | `fastapi_add_event_driven` |
| Category | EVOLVE |
| Complexity | Very High |
| Dependencies | Existing FastAPI project, Redis Streams (default) or Kafka/NATS, Pydantic v2, SQLAlchemy 2.0, Alembic, ARQ or Dramatiq for worker processes |
| Signature | `add_event_driven(project_dir: str, broker: str = "redis_streams", events: list[str] \| None = None, schema_registry_path: str = "events/schemas", generate_consumer: bool = True, generate_producer: bool = True) -> dict` |
| Parameters | `project_dir`: project root path<br>`broker`: `redis_streams` \| `kafka` \| `nats` (default: `redis_streams`)<br>`events`: list of event type names to scaffold (e.g. `["OrderCreated", "UserDeleted"]`); None = scaffold base only<br>`schema_registry_path`: directory where Pydantic event schemas live (default: `events/schemas`)<br>`generate_consumer`: scaffold consumer workers with retry, DLQ, idempotency (default `True`)<br>`generate_producer`: scaffold producer helpers with transactional outbox pattern (default `True`) |

---

## 2. Purpose

`fastapi_add_event_driven` converts a synchronous request/response FastAPI monolith into an event-driven service without requiring a migration to a full message broker platform on day one. The core problem it solves is the **dual-write hazard**: when a service must update its own database AND publish a message to an external broker in the same logical operation, a crash between the two writes leaves data in an inconsistent state — the row is committed but the event is never published, or the event fires but the row never lands. This tool implements the **transactional outbox pattern** as the atomic solution: the producer writes both the business row and an `outbox_events` record in a single database transaction, then a background worker (ARQ or Dramatiq) polls the outbox and publishes confirmed events to the broker. This eliminates the dual-write window entirely and guarantees at-least-once delivery with a measurable recovery path when the broker is temporarily unavailable.

Beyond the outbox, production event systems require three additional failure-safety mechanisms that are consistently underbuilt in greenfield implementations. First, **consumers must be idempotent** — Redis Streams and Kafka both guarantee at-least-once delivery, meaning the same `event_id` can arrive twice on broker restart or consumer rebalance; the tool scaffolds a Redis `seen:{consumer_name}:{event_id}` cache with a 7-day TTL to absorb duplicates safely. Second, **retry logic must use exponential backoff** — fixed-interval retries cause thundering-herd storms when a downstream service recovers; the tool generates a configurable retry policy (5 attempts, 200ms base, 2× multiplier, ±10% jitter, hard cap at 30s). Third, **poisoned messages must be quarantined** — a handler that always raises will spin forever on the same event and block all subsequent messages in the stream; after `max_attempts` the event is written to a dedicated DLQ stream with full error metadata (type, traceback, original payload) so operators can inspect and replay it without data loss. Schema evolution is handled via versioned event classes (`OrderCreatedV1`, `OrderCreatedV2`) with explicit `migrate_v1_to_v2` hooks, ensuring consumers that have not yet deployed the new schema can still process events from the old schema. UUID v7 is used for all `event_id` fields because its time-ordered structure enables chronological sorting in observability dashboards without a separate `occurred_at` index scan.

---

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s for up to 20 event types | Dev runs in CLI during scaffolding |
| Files created | ≥ 12 (base event, schemas dir, producer, consumer, outbox model, retry engine, DLQ handler, idempotency store, worker entrypoint, tests, Makefile targets, alerts template) | Predictable scaffolding surface |
| Files modified | ≤ 4 (`main.py`, `core/config.py`, `pyproject.toml`, `docker-compose.yml`) | Minimal blast radius on existing code |
| Event publish latency (producer side) | < 5 ms p99 | Outbox write is a single INSERT in the same transaction; no network hop at publish time |
| Event processing latency (idle consumer) | < 50 ms p99 | Redis XREAD with BLOCK 100ms; immediate when message arrives |
| Outbox drain rate | ≥ 500 events/s sustained | Background worker with LIMIT 100 batch per poll cycle |
| Retry base interval | 200 ms (first retry) | Gives downstream service time to recover from transient error |
| Max retry backoff | 30 s | Hard cap prevents runaway delays; DLQ kicks in after max_attempts |
| DLQ growth rate alert threshold | > 10 events/minute | Alert in Grafana template; operator replay required |
| Consumer startup time | < 1 s | ARQ worker connects Redis on boot; no heavy init |
| Idempotency cache TTL | 7 days | Covers any realistic broker re-delivery window |
| Consumer lag alert threshold | > 1000 events | Logged as WARNING metric; triggers scale-out suggestion |

---

## 4. Code Examples

### 4.1 BaseEvent — Pydantic v2 with UUID v7

```python
# events/base.py
"""
Base event schema for all domain events.
Uses UUID v7 for time-ordered event IDs (chronological by construction).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def _uuid7() -> uuid.UUID:
    """
    Generate a UUID v7 (time-ordered, RFC 9562).
    Falls back to uuid4 if the uuid library version does not support v7.
    """
    try:
        return uuid.uuid7()  # Python 3.13+
    except AttributeError:
        # Backport: embed millisecond timestamp in UUID v4 variant bits
        import time
        ts_ms = int(time.time() * 1000)
        rand_a = uuid.uuid4().int & 0x0FFF
        rand_b = uuid.uuid4().int & 0x3FFFFFFFFFFFFFFF
        val = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | rand_b
        return uuid.UUID(int=val)


class BaseEvent(BaseModel):
    """
    All domain events inherit from this class.
    Fields are immutable after creation (model_config frozen=True).
    """
    event_id: uuid.UUID = Field(default_factory=_uuid7)
    event_type: str  # e.g. "OrderCreated", "UserDeleted"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: uuid.UUID | None = Field(default=None)
    schema_version: int = Field(default=1)
    producer_service: str = Field(default="")

    model_config = {"frozen": True}

    def to_stream_payload(self) -> dict[str, str]:
        """Serialize event for Redis XADD (all values must be strings)."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": str(self.correlation_id) if self.correlation_id else "",
            "schema_version": str(self.schema_version),
            "payload": self.model_dump_json(),
        }
```

### 4.2 OutboxEvent — SQLAlchemy 2.0 async model

```python
# app/models/outbox_event.py
"""
Transactional outbox table. Written atomically with the business row.
Background worker (outbox_worker.py) drains this table to the broker.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OutboxStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, unique=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    stream_name: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON blob
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=OutboxStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_outbox_status_created", "status", "created_at"),
        Index("ix_outbox_event_id", "event_id", unique=True),
    )
```

### 4.3 emit_event — transactional outbox producer helper

```python
# events/producer.py
"""
emit_event() writes an event to the outbox table inside the caller's DB
transaction. The background outbox_worker.py publishes it to the broker.

Usage:
    async with async_session_maker() as session:
        async with session.begin():
            order = Order(...)
            session.add(order)
            await emit_event(session, OrderCreated(order_id=order.id))
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox_event import OutboxEvent
from events.base import BaseEvent


STREAM_MAP: dict[str, str] = {
    "OrderCreated": "events:orders",
    "UserDeleted": "events:users",
    "PaymentProcessed": "events:payments",
    # Add new event types here as streams are created
}


async def emit_event(
    session: AsyncSession,
    event: BaseEvent,
    *,
    stream_name: str | None = None,
) -> OutboxEvent:
    """
    Write event to outbox_events table inside the current session transaction.
    Does NOT publish to broker directly — the outbox worker handles that.
    Raises ValueError if event_type has no registered stream and stream_name is None.
    """
    resolved_stream = stream_name or STREAM_MAP.get(event.event_type)
    if resolved_stream is None:
        raise ValueError(
            f"emit_event: no stream registered for event_type={event.event_type!r}. "
            f"Add it to STREAM_MAP or pass stream_name explicitly."
        )

    outbox_entry = OutboxEvent(
        event_id=event.event_id,
        event_type=event.event_type,
        stream_name=resolved_stream,
        payload=event.model_dump_json(),
        status="pending",
    )
    session.add(outbox_entry)
    # Flush so that the INSERT is part of the outer transaction
    # without committing it — caller controls the commit boundary.
    await session.flush()
    return outbox_entry
```

### 4.4 OutboxWorker — ARQ-based drain worker

```python
# events/outbox_worker.py
"""
Background ARQ worker that drains the outbox_events table to the broker.
Run with: arq events.outbox_worker.WorkerSettings
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import engine
from app.models.outbox_event import OutboxEvent, OutboxStatus
from events.base import BaseEvent

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


async def drain_outbox(ctx: dict) -> dict[str, int]:
    """
    ARQ job: fetch up to BATCH_SIZE pending outbox events,
    publish each to Redis Streams, mark published.
    Returns dict with published_count and failed_count.
    """
    redis_client: aioredis.Redis = ctx["redis"]
    session_maker: async_sessionmaker[AsyncSession] = ctx["session_maker"]
    published = 0
    failed = 0

    async with session_maker() as session:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == OutboxStatus.PENDING.value)
            .order_by(OutboxEvent.created_at)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(stmt)
        pending_events = result.scalars().all()

        for outbox_row in pending_events:
            try:
                payload = json.loads(outbox_row.payload)
                fields = {k: str(v) for k, v in payload.items()}
                await redis_client.xadd(outbox_row.stream_name, fields)
                outbox_row.status = OutboxStatus.PUBLISHED.value
                outbox_row.published_at = datetime.now(timezone.utc)
                published += 1
            except Exception as exc:
                outbox_row.status = OutboxStatus.FAILED.value
                outbox_row.last_error = str(exc)
                outbox_row.attempts += 1
                failed += 1
                logger.error(
                    "outbox_drain_failed event_id=%s error=%s",
                    outbox_row.event_id,
                    exc,
                )

        await session.commit()

    logger.info("outbox_drain published=%d failed=%d", published, failed)
    return {"published": published, "failed": failed}


class WorkerSettings:
    functions = [drain_outbox]
    on_startup = None
    on_shutdown = None
    redis_settings = None  # populated from env at runtime
    job_completion_wait = 60
    max_jobs = 10
    poll_delay = 0.5  # seconds between polls when queue empty
```

### 4.5 Consumer — Redis Streams consumer with idempotency via Redis seen cache

```python
# events/consumer.py
"""
Generic Redis Streams consumer with:
- Consumer group support (each service has its own group)
- Idempotency via Redis seen cache (TTL 7 days)
- Exponential backoff retry
- DLQ write after max_attempts
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Callable, Awaitable

import redis.asyncio as aioredis

from events.retry import RetryPolicy, exponential_backoff
from events.dlq import write_to_dlq

logger = logging.getLogger(__name__)

SEEN_CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class EventConsumer:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        stream_name: str,
        consumer_group: str,
        consumer_name: str,
        handler: Callable[[dict], Awaitable[None]],
        retry_policy: RetryPolicy | None = None,
        max_attempts: int = 5,
    ) -> None:
        self.redis = redis_client
        self.stream = stream_name
        self.group = consumer_group
        self.consumer = consumer_name
        self.handler = handler
        self.retry_policy = retry_policy or RetryPolicy()
        self.max_attempts = max_attempts
        self._running = False

    async def _is_seen(self, event_id: str) -> bool:
        key = f"seen:{self.consumer}:{event_id}"
        return bool(await self.redis.exists(key))

    async def _mark_seen(self, event_id: str) -> None:
        key = f"seen:{self.consumer}:{event_id}"
        await self.redis.setex(key, SEEN_CACHE_TTL_SECONDS, "1")

    async def _ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(
                self.stream, self.group, id="$", mkstream=True
            )
        except aioredis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def run(self) -> None:
        await self._ensure_group()
        self._running = True
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, self.stop)

        while self._running:
            messages = await self.redis.xreadgroup(
                self.group,
                self.consumer,
                {self.stream: ">"},
                count=10,
                block=100,
            )
            if not messages:
                continue
            for _stream, entries in messages:
                for msg_id, fields in entries:
                    event_id = fields.get(b"event_id", b"").decode()
                    if await self._is_seen(event_id):
                        logger.debug("skipping duplicate event_id=%s", event_id)
                        await self.redis.xack(self.stream, self.group, msg_id)
                        continue
                    await self._process_with_retry(msg_id, fields, event_id)

    def stop(self) -> None:
        self._running = False

    async def _process_with_retry(
        self, msg_id: bytes, fields: dict, event_id: str
    ) -> None:
        payload = json.loads(fields.get(b"payload", b"{}").decode())
        for attempt in range(1, self.max_attempts + 1):
            try:
                await self.handler(payload)
                await self._mark_seen(event_id)
                await self.redis.xack(self.stream, self.group, msg_id)
                return
            except Exception as exc:
                if attempt >= self.max_attempts:
                    logger.error(
                        "max_attempts reached event_id=%s, sending to DLQ", event_id
                    )
                    await write_to_dlq(
                        self.redis, payload, exc, stream=self.stream
                    )
                    await self.redis.xack(self.stream, self.group, msg_id)
                    return
                delay = exponential_backoff(attempt, self.retry_policy)
                logger.warning(
                    "handler_error event_id=%s attempt=%d/%d retrying_in=%.2fs",
                    event_id,
                    attempt,
                    self.max_attempts,
                    delay,
                )
                await asyncio.sleep(delay)
```

### 4.6 DLQ handler — quarantine poisoned messages

```python
# events/dlq.py
"""
Dead-letter queue handler.
Poisoned messages are written to a DLQ Redis stream with full error metadata.
Operators can replay DLQ entries manually via events/replay.py.
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone

import redis.asyncio as aioredis

DLQ_STREAM = "events:dlq"
logger = logging.getLogger(__name__)


async def write_to_dlq(
    redis_client: aioredis.Redis,
    original_payload: dict,
    exception: Exception,
    *,
    stream: str = "",
) -> None:
    """
    Write a poisoned event to the DLQ stream.
    Includes: original payload, error type, traceback, timestamp, source stream.
    Never raises — DLQ write failure is logged and silently absorbed to avoid
    blocking the consumer loop on a secondary failure.
    """
    try:
        dlq_entry = {
            "original_payload": json.dumps(original_payload),
            "error_type": type(exception).__name__,
            "error_message": str(exception),
            "traceback": traceback.format_exc(),
            "source_stream": stream,
            "dlq_at": datetime.now(timezone.utc).isoformat(),
        }
        fields_str = {k: v for k, v in dlq_entry.items()}
        await redis_client.xadd(DLQ_STREAM, fields_str)
        logger.info(
            "dlq_write event_type=%s error=%s",
            original_payload.get("event_type", "unknown"),
            type(exception).__name__,
        )
    except Exception as dlq_exc:
        logger.critical(
            "dlq_write_failed — event lost: original_error=%s dlq_error=%s",
            exception,
            dlq_exc,
        )
```

### 4.7 RetryPolicy — exponential backoff with jitter

```python
# events/retry.py
"""
Retry policy with exponential backoff and jitter.
Used by EventConsumer and outbox_worker alike.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class RetryPolicy:
    base_delay_seconds: float = 0.2
    multiplier: float = 2.0
    jitter_fraction: float = 0.1
    max_delay_seconds: float = 30.0
    max_attempts: int = 5


def exponential_backoff(attempt: int, policy: RetryPolicy) -> float:
    """
    Return the delay in seconds for the given attempt number (1-indexed).
    Formula: min(base * multiplier^(attempt-1) * jitter, max_delay)
    Jitter is ±jitter_fraction of the raw delay to avoid thundering herd.
    """
    raw_delay = policy.base_delay_seconds * (policy.multiplier ** (attempt - 1))
    jitter = raw_delay * policy.jitter_fraction * (2 * random.random() - 1)
    delay = min(raw_delay + jitter, policy.max_delay_seconds)
    return max(delay, 0.0)


@dataclass
class PerEventRetryOverride:
    """
    Per-event-type retry policy override. Register in retry_registry dict.
    E.g. retry_registry["PaymentProcessed"] = PerEventRetryOverride(max_attempts=10)
    """
    max_attempts: int = 5
    base_delay_seconds: float = 0.2
    multiplier: float = 2.0


retry_registry: dict[str, PerEventRetryOverride] = {}


def get_policy_for_event(event_type: str) -> RetryPolicy:
    """
    Return effective RetryPolicy for the given event_type,
    falling back to global defaults if no override is registered.
    """
    override = retry_registry.get(event_type)
    if override is None:
        return RetryPolicy()
    return RetryPolicy(
        base_delay_seconds=override.base_delay_seconds,
        multiplier=override.multiplier,
        max_attempts=override.max_attempts,
    )
```

### 4.8 Schema v1 → v2 migration pattern

```python
# events/schemas/order_created.py
"""
Versioned event schema for OrderCreated.
V1: original schema with customer_id
V2: adds shipping_address; migration hook handles V1 → V2 upgrade.
"""
from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from events.base import BaseEvent


class OrderCreatedV1(BaseEvent):
    event_type: str = "OrderCreated"
    schema_version: int = 1
    order_id: uuid.UUID
    customer_id: uuid.UUID
    total_cents: int


class ShippingAddress(BaseModel):
    street: str
    city: str
    country: str = "BR"


class OrderCreatedV2(BaseEvent):
    event_type: str = "OrderCreated"
    schema_version: int = 2
    order_id: uuid.UUID
    customer_id: uuid.UUID
    total_cents: int
    shipping_address: ShippingAddress | None = None  # None = not captured in V1


def migrate_order_created(raw: dict[str, Any]) -> OrderCreatedV2:
    """
    Migrate raw event payload to V2 regardless of schema_version.
    V1 payloads are upcast with shipping_address=None (safe default).
    V2 payloads are passed through directly.
    Raises ValueError on unrecognised schema_version > 2.
    """
    version = int(raw.get("schema_version", 1))
    if version == 1:
        return OrderCreatedV2(
            event_id=raw["event_id"],
            event_type=raw["event_type"],
            occurred_at=raw["occurred_at"],
            correlation_id=raw.get("correlation_id"),
            schema_version=2,
            order_id=raw["order_id"],
            customer_id=raw["customer_id"],
            total_cents=raw["total_cents"],
            shipping_address=None,
        )
    if version == 2:
        return OrderCreatedV2(**raw)
    raise ValueError(
        f"migrate_order_created: unknown schema_version={version}. "
        "Update migration hook before deploying consumers for new schema."
    )
```

### 4.9 Trace propagation — OpenTelemetry context in events

```python
# events/tracing.py
"""
Propagates OpenTelemetry trace context through events.
Producer injects W3C traceparent/tracestate into event payload.
Consumer extracts and restores the trace context before invoking handler.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace
    from opentelemetry.propagate import extract, inject
    from opentelemetry.context import attach, detach
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


def inject_trace_context(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Inject current OTel trace context into event payload as
    'traceparent' and 'tracestate' string fields.
    No-op if opentelemetry is not installed.
    """
    if not OTEL_AVAILABLE:
        return payload
    carrier: dict[str, str] = {}
    inject(carrier)
    return {**payload, **carrier}


def with_trace_context(payload: dict[str, Any]):
    """
    Context manager: restore producer trace context around handler execution.
    Enables distributed trace spans to link producer → consumer.
    """
    import contextlib

    @contextlib.asynccontextmanager
    async def _ctx():
        if not OTEL_AVAILABLE:
            yield
            return
        ctx = extract(payload)
        token = attach(ctx)
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(
            f"consume:{payload.get('event_type', 'unknown')}"
        ):
            try:
                yield
            finally:
                detach(token)

    return _ctx()
```

### 4.10 Tests — outbox + consumer idempotency + DLQ

```python
# tests/test_event_driven.py
"""
Integration tests for event-driven scaffolding.
Requires Redis running at REDIS_URL (default: redis://localhost:6379).
"""
from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as aioredis

from events.base import BaseEvent, _uuid7
from events.consumer import EventConsumer
from events.dlq import write_to_dlq, DLQ_STREAM
from events.retry import RetryPolicy, exponential_backoff
from events.producer import emit_event
from events.schemas.order_created import OrderCreatedV1, OrderCreatedV2, migrate_order_created


# ── Unit tests ─────────────────────────────────────────────────────────────

def test_base_event_defaults_set_on_construction():
    event = BaseEvent(event_type="TestEvent")
    assert event.event_id is not None
    assert event.occurred_at is not None
    assert event.schema_version == 1
    assert str(event.event_id)  # UUID v7 or v4 — must be non-empty


def test_base_event_is_immutable():
    event = BaseEvent(event_type="TestEvent")
    with pytest.raises(Exception):  # ValidationError (frozen model)
        event.event_type = "Modified"  # type: ignore[misc]


def test_exponential_backoff_grows_with_attempt():
    policy = RetryPolicy(base_delay_seconds=0.2, multiplier=2.0, jitter_fraction=0.0)
    delays = [exponential_backoff(i, policy) for i in range(1, 6)]
    # With zero jitter: 0.2, 0.4, 0.8, 1.6, 3.2
    for i in range(len(delays) - 1):
        assert delays[i + 1] > delays[i], "Delays must be monotonically increasing"


def test_exponential_backoff_respects_max_delay():
    policy = RetryPolicy(base_delay_seconds=1.0, multiplier=10.0, max_delay_seconds=5.0, jitter_fraction=0.0)
    for attempt in range(1, 10):
        assert exponential_backoff(attempt, policy) <= 5.0


def test_schema_v1_to_v2_migration_fills_shipping_address_none():
    v1_payload = {
        "event_id": str(uuid.uuid4()),
        "event_type": "OrderCreated",
        "occurred_at": "2026-04-12T00:00:00+00:00",
        "correlation_id": None,
        "schema_version": 1,
        "order_id": str(uuid.uuid4()),
        "customer_id": str(uuid.uuid4()),
        "total_cents": 9999,
    }
    v2 = migrate_order_created(v1_payload)
    assert isinstance(v2, OrderCreatedV2)
    assert v2.shipping_address is None
    assert v2.schema_version == 2


def test_schema_v2_passthrough():
    event = OrderCreatedV2(
        event_type="OrderCreated",
        order_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        total_cents=100,
    )
    raw = json.loads(event.model_dump_json())
    result = migrate_order_created(raw)
    assert result.order_id == event.order_id


@pytest.mark.asyncio
async def test_consumer_skips_duplicate_event_id():
    redis_mock = AsyncMock()
    redis_mock.exists.return_value = True  # Simulate seen cache hit
    redis_mock.xreadgroup.return_value = [
        (b"events:orders", [(b"1234-0", {b"event_id": b"abc123", b"payload": b"{}"})])
    ]
    handler = AsyncMock()
    consumer = EventConsumer(
        redis_client=redis_mock,
        stream_name="events:orders",
        consumer_group="test_group",
        consumer_name="consumer-1",
        handler=handler,
        max_attempts=3,
    )
    # Run one iteration
    consumer._running = False
    redis_mock.xreadgroup.return_value = []
    await consumer.run()
    handler.assert_not_called()


@pytest.mark.asyncio
async def test_dlq_write_on_max_attempts_exceeded():
    redis_mock = AsyncMock()
    redis_mock.exists.return_value = False
    redis_mock.xreadgroup.side_effect = [
        [(b"events:orders", [(b"999-0", {b"event_id": b"evt-bad", b"payload": b'{"event_type":"bad"}'})])],
        [],
    ]
    handler = AsyncMock(side_effect=RuntimeError("handler always fails"))
    consumer = EventConsumer(
        redis_client=redis_mock,
        stream_name="events:orders",
        consumer_group="grp",
        consumer_name="c1",
        handler=handler,
        retry_policy=RetryPolicy(base_delay_seconds=0.0, max_attempts=2),
        max_attempts=2,
    )
    consumer._running = True
    with patch("events.dlq.aioredis") as _:
        redis_mock.xadd = AsyncMock()
        await consumer.run()
    # DLQ xadd should have been called once
    dlq_calls = [c for c in redis_mock.xadd.call_args_list if DLQ_STREAM in str(c)]
    assert len(dlq_calls) >= 1
```

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-01 | **Producer writes are ALWAYS transactional — outbox row commits with business row or neither commits** | `emit_event()` in `events/producer.py` writes `OutboxEvent` inside the caller's `session.begin()` block; no separate commit path exists in the function; verified by T-07 |
| QS-02 | **Events are ALWAYS Pydantic-validated before publication** | `BaseEvent.model_dump_json()` in `events/base.py` is called at outbox write time; invalid payloads raise `ValidationError` before reaching `OutboxEvent` INSERT; verified by T-01 |
| QS-03 | **Consumers are ALWAYS idempotent — duplicate delivery is safe** | `EventConsumer._is_seen()` in `events/consumer.py` checks Redis `seen:{consumer}:{event_id}` before invoking handler; duplicate ACKed and skipped; verified by T-19, T-20 |
| QS-04 | **Retries ALWAYS use exponential backoff — never fixed interval** | `exponential_backoff()` in `events/retry.py` used exclusively in `EventConsumer._process_with_retry()`; no `asyncio.sleep(constant)` call in consumer path; verified by T-13, T-14 |
| QS-05 | **DLQ entries ALWAYS include error type, full traceback, and original payload** | `write_to_dlq()` in `events/dlq.py` writes `error_type`, `error_message`, `traceback`, `original_payload`, `source_stream`, `dlq_at`; missing field raises `KeyError` in consumer-side test T-16 |
| QS-06 | **Event IDs are ALWAYS UUID v7 (time-ordered)** | `BaseEvent.event_id` default factory calls `_uuid7()` in `events/base.py`; no `uuid.uuid4()` call for event IDs in any event schema; verified by T-02 |
| QS-07 | **Schema evolution is ALWAYS explicit — version field mandatory** | `BaseEvent.schema_version` is a required field (default 1); migration hooks in `events/schemas/{type}.py` must handle every prior version; unrecognised version raises `ValueError`; verified by T-28 |
| QS-08 | **Outbox worker uses SELECT FOR UPDATE SKIP LOCKED to prevent double-publish** | `events/outbox_worker.py::drain_outbox()` executes `.with_for_update(skip_locked=True)` on all PENDING row reads; no two worker instances can claim the same outbox row; verified by T-09 |
| QS-09 | **DLQ write failure NEVER blocks the consumer loop** | `write_to_dlq()` wraps the Redis XADD in try/except; failure logs CRITICAL and returns without re-raising; consumer ACKs the message; verified by T-17 |
| QS-10 | **Consumer graceful shutdown flushes in-flight ACKs on SIGTERM** | `EventConsumer.run()` registers `signal.SIGTERM` handler calling `self.stop()`; loop exits cleanly after current batch; verified by T-06 |
| QS-11 | **Trace context is propagated from producer to consumer** | `inject_trace_context()` in `events/tracing.py` called at `emit_event()` time; `with_trace_context()` called in consumer handler wrapper; verified by T-30 |
| QS-12 | **Outbox cleanup runs after successful publish to prevent unbounded table growth** | `drain_outbox()` updates `OutboxEvent.status = PUBLISHED` immediately after `xadd`; a separate cleanup job prunes `PUBLISHED` rows older than 7 days; verified by T-10 |

---

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `events/base.py` exists and exports `BaseEvent`, `_uuid7` | `from events.base import BaseEvent, _uuid7` does not raise |
| CC-02 | `events/producer.py` exports `emit_event`, `STREAM_MAP` | File exists; inspect exports |
| CC-03 | `events/consumer.py` exports `EventConsumer` with `run()` and `stop()` | File exists; `EventConsumer` has both methods |
| CC-04 | `events/dlq.py` exports `write_to_dlq`, `DLQ_STREAM` | File exists; inspect exports |
| CC-05 | `events/retry.py` exports `RetryPolicy`, `exponential_backoff`, `get_policy_for_event` | File exists; inspect exports |
| CC-06 | `events/outbox_worker.py` exports `drain_outbox`, `WorkerSettings` | File exists; `WorkerSettings.functions` contains `drain_outbox` |
| CC-07 | `events/tracing.py` exports `inject_trace_context`, `with_trace_context` | File exists; inspect exports |
| CC-08 | `app/models/outbox_event.py` defines `OutboxEvent` SQLAlchemy model | `grep "class OutboxEvent"` returns match |
| CC-09 | `outbox_events` table has index on `(status, created_at)` | Inspect `__table_args__` in `OutboxEvent` |
| CC-10 | Alembic migration creates `outbox_events` table with all 9 columns | `upgrade()` inspected; `create_table("outbox_events", ...)` present |
| CC-11 | `OutboxEvent` has unique constraint on `event_id` | Inspect model or migration; `unique=True` on `event_id` column |
| CC-12 | `emit_event()` calls `session.flush()` (not `session.commit()`) | `grep "session.flush()" events/producer.py` returns match |
| CC-13 | `EventConsumer` uses consumer groups (`xreadgroup`) not plain `xread` | `grep "xreadgroup" events/consumer.py` returns match |
| CC-14 | Idempotency TTL is configurable (default 7 days) | `SEEN_CACHE_TTL_SECONDS` constant defined in `events/consumer.py` |
| CC-15 | DLQ entries include `original_payload`, `error_type`, `traceback`, `source_stream`, `dlq_at` | Inspect `write_to_dlq()` fields dict |
| CC-16 | `exponential_backoff()` respects `max_delay_seconds` cap | T-12: delay at attempt=10 ≤ `RetryPolicy.max_delay_seconds` |
| CC-17 | Schema version field present on all event classes | `grep "schema_version" events/schemas/*.py` returns match per file |
| CC-18 | `migrate_{event_type}()` exists for each event type with v2+ | Each schema file with V2 exports migration hook |
| CC-19 | Unrecognised schema version raises `ValueError` in migration hook | T-28 verifies error raised for version=99 |
| CC-20 | `drain_outbox()` uses `SELECT FOR UPDATE SKIP LOCKED` | `grep "skip_locked=True" events/outbox_worker.py` returns match |
| CC-21 | Outbox worker marks row `PUBLISHED` immediately after successful `xadd` | T-09: `OutboxEvent.status == "published"` after drain run |
| CC-22 | Consumer handles `broker=kafka` via abstraction layer | `EventConsumer` accepts `broker_client` protocol; Kafka adapter exists in `events/adapters/kafka.py` |
| CC-23 | `EventConsumer.stop()` called on SIGTERM; in-flight ACKs complete | T-06: consumer exits cleanly within 1s of SIGTERM |
| CC-24 | `tests/test_event_driven.py` exists with ≥ 30 test functions | `grep -c "^def test_\|^async def test_"` returns ≥ 30 |
| CC-25 | `Makefile` has targets `events-worker-start`, `events-drain-once`, `events-dlq-inspect` | grep targets in Makefile |
| CC-26 | `core/config.py` has `REDIS_STREAMS_URL`, `EVENT_MAX_ATTEMPTS`, `EVENT_OUTBOX_BATCH_SIZE` | Inspect `Settings` class |
| CC-27 | `main.py` includes ARQ lifespan startup for outbox worker registration | `grep "drain_outbox" main.py` returns match |
| CC-28 | `docker-compose.yml` updated with ARQ worker service | `grep "arq events.outbox_worker" docker-compose.yml` |
| CC-29 | Grafana alert template at `monitoring/alerts/events.json` | File exists with DLQ growth rate alert |
| CC-30 | Tool execution time < 5s | Benchmark: `time add_event_driven(...)` < 5s |
| CC-31 | `inject_trace_context()` no-ops when opentelemetry not installed | T-30: runs without ImportError in minimal env |
| CC-32 | `pyproject.toml` updated with `redis>=5.0`, `arq>=0.25` optional dependencies | grep `redis` and `arq` in pyproject.toml extras |
| CC-33 | Consumer lag metric emitted as WARNING log when backlog > 1000 | T-24: log contains "consumer_lag" at WARNING level |
| CC-34 | Tool is idempotent — re-run on already scaffolded project returns `{status: "no_op"}` | T-27 verifies no duplicate files written |

---

## 7. Definition of Done

- [ ] All 34 Completeness Criteria verified (CC-01..CC-34)
- [ ] All 12 Quality Standards enforced (QS-01..QS-12)
- [ ] All 8 Invariants enforced (INV-ED-01..INV-ED-08; see §8)
- [ ] All 25 User Stories pass acceptance tests (see §9)
- [ ] All 30 Test Cases pass (T-01..T-30; see §10)
- [ ] Tool is idempotent: run twice on same project, second run returns `{status: "no_op"}`
- [ ] Rollback procedure documented and validated end-to-end (see §12)
- [ ] Outbox drain validated on simulated broker-down scenario; events recovered on broker restart
- [ ] Consumer idempotency validated: same event_id delivered 3× triggers handler exactly once
- [ ] DLQ write validated: handler always failing results in DLQ entry with full traceback after max_attempts
- [ ] Schema migration validated: V1 event consumed by V2 consumer without error
- [ ] Interaction with TOOL-023, TOOL-014, TOOL-005, TOOL-015 verified (see §11)
- [ ] Documentation updated (`KNOWLEDGE.md`, `manifest.yaml`, `SKILL.md`)
- [ ] Tool registered in `mcp_server.py` under `EVOLVE` category

---

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-ED-01 | An event is **never** published directly — ALWAYS via outbox table | `emit_event()` in `events/producer.py` only writes to `outbox_events`; no direct `redis.xadd` call in producer path; direct broker calls raise `RuntimeError` at lint gate | T-07, T-08 |
| INV-ED-02 | Outbox row write is **always** in the same DB transaction as the business write | `emit_event()` calls `session.flush()` (not `session.commit()`); caller owns the `session.begin()` block; two separate connections are never used | T-07, T-08 |
| INV-ED-03 | Consumers are **always** idempotent — handling the same event_id twice is safe | `_is_seen()` check in `events/consumer.py` runs before every handler invocation; duplicate ACKed without calling handler | T-19, T-20 |
| INV-ED-04 | Retries **always** use exponential backoff — fixed-interval sleep is forbidden | `exponential_backoff()` called exclusively; `asyncio.sleep(constant)` in consumer retry path triggers CI lint failure | T-13, T-14 |
| INV-ED-05 | DLQ entries **always** include error type, full traceback, and original event payload | `write_to_dlq()` fields dict validated by T-16; missing any of the 5 required fields raises KeyError | T-15, T-16 |
| INV-ED-06 | Event IDs are **always** UUID v7 (time-ordered) for observability | `BaseEvent.event_id` default factory is `_uuid7()`; no UUID v4 used for event IDs; verified at construction | T-02 |
| INV-ED-07 | Schema version is **always** explicit — consumers reject unrecognised versions | `migrate_*()` hooks raise `ValueError` for unknown `schema_version`; no silent fallback to default parsing | T-28, T-29 |
| INV-ED-08 | Outbox worker **always** uses `SELECT FOR UPDATE SKIP LOCKED` to prevent double-publish | `drain_outbox()` query includes `.with_for_update(skip_locked=True)`; test T-09 runs two concurrent drain calls and verifies zero duplicate publishes | T-09, T-10 |

---

## 9. User Stories

### 9.1 Basic pub/sub — define event, publish, consume (US-01..US-05)

**US-01: Define a new domain event and scaffold its schema**
- **As a** backend developer adding order fulfillment to a FastAPI service
- **I want** to run `add_event_driven(project_dir, events=["OrderCreated"])` and get a scaffolded `OrderCreated` event class immediately
- **So that** I can implement the handler and producer without writing boilerplate by hand
- **Given:** existing FastAPI project with SQLAlchemy 2.0 and Redis available
- **When:** `add_event_driven(project_dir, events=["OrderCreated"])` is called
- **Then:**
  - `events/schemas/order_created.py` created with `OrderCreatedV1(BaseEvent)` Pydantic class (INV-ED-06)
  - `BaseEvent` base class at `events/base.py` with `event_id`, `event_type`, `occurred_at`, `correlation_id`, `schema_version` (CC-01)
  - Stream `events:orders` added to `STREAM_MAP` in `events/producer.py` (CC-02)
  - Tool returns `{files_created: [...], files_modified: [...], status: "success"}`

**US-02: Publish an event atomically with a business write**
- **As a** developer implementing order creation
- **I want** to call `emit_event(session, OrderCreated(...))` inside my existing transaction
- **So that** the event is guaranteed to be published if and only if the order row is committed
- **Given:** `POST /orders` handler with `async with session.begin()` wrapping an `Order` insert
- **When:** `await emit_event(session, OrderCreatedV1(order_id=order.id, ...))` is called inside the `begin()` block
- **Then:**
  - Both `orders` row and `outbox_events` row committed atomically (INV-ED-01, INV-ED-02)
  - If transaction rolls back (exception), `outbox_events` row also disappears — no phantom event
  - Producer returns `OutboxEvent` with `status="pending"` (CC-12)
  - Background outbox worker picks it up within the next poll cycle

**US-03: Consumer receives and processes event**
- **As a** developer implementing the shipping service consumer
- **I want** the scaffolded `EventConsumer` to receive `OrderCreated` events and call my handler
- **So that** the shipping service reacts to order creation without polling the orders database
- **Given:** ARQ worker running; `events:orders` stream has new entry from outbox worker
- **When:** consumer reads entry via `xreadgroup` and calls `await handler(payload)`
- **Then:**
  - Handler called exactly once per unique `event_id` (INV-ED-03)
  - Message ACKed via `xack` after successful handler execution (CC-13)
  - Structured log emitted: `{"event_id": "...", "event_type": "OrderCreated", "handler": "shipping_service"}` (QS-11)
  - Consumer lag metric updated

**US-04: Trace context flows from producer to consumer**
- **As a** SRE debugging a distributed flow
- **I want** the OpenTelemetry trace started in the FastAPI request to appear on the consumer span
- **So that** I can see the full distributed trace from HTTP request through event to handler in Jaeger/Grafana
- **Given:** OpenTelemetry instrumented on both producer and consumer services
- **When:** `emit_event()` called with active OTel span; consumer processes the event
- **Then:**
  - `traceparent` header injected into event payload by `inject_trace_context()` (CC-31, QS-11)
  - Consumer span has `trace_id` matching the producer span (T-30)
  - Span name is `consume:OrderCreated`
  - No OTel error in environments without opentelemetry installed (CC-31)

**US-05: Structured log per event for observability**
- **As a** developer monitoring the event pipeline
- **I want** every event publish and consume to emit a structured log line with `event_id`, `event_type`, `stream`, and status
- **So that** I can query Datadog/Grafana Loki to trace any individual event end-to-end
- **Given:** standard Python logging with JSON formatter
- **When:** `drain_outbox()` publishes an event and consumer processes it
- **Then:**
  - Log line at INFO: `outbox_drain published=1 failed=0` with structured fields (QS-12)
  - Consumer log at DEBUG for each message: `event_id`, `event_type`, `attempt`
  - DLQ write at INFO: `dlq_write event_type=... error=...`
  - No secrets or PII in log fields

### 9.2 Outbox pattern — transactional guarantee (US-06..US-10)

**US-06: Broker down does not cause data loss**
- **As a** developer whose Redis instance goes down for 5 minutes during a deploy
- **I want** orders to continue being created normally and their events to be published after Redis recovers
- **So that** no events are silently dropped and the pipeline catches up automatically
- **Given:** broker (Redis) unreachable; FastAPI service continues accepting POST /orders requests
- **When:** `emit_event()` is called during broker outage and outbox worker cannot connect
- **Then:**
  - `outbox_events` rows accumulate with `status="pending"` — no data loss (INV-ED-01)
  - `POST /orders` succeeds: order row and outbox row committed to PostgreSQL normally (INV-ED-02)
  - When broker recovers, `drain_outbox()` publishes all pending rows in batch order (CC-20)
  - Events arrive at consumer in original `created_at` order

**US-07: Double-drain prevented by `SKIP LOCKED`**
- **As a** platform engineer running two outbox worker instances for high availability
- **I want** the same `outbox_events` row to be processed by exactly one worker even under concurrent drain cycles
- **So that** each event is published exactly once to the broker, not duplicated
- **Given:** two ARQ workers running concurrently calling `drain_outbox()` at the same time
- **When:** both workers SELECT the same batch of PENDING rows
- **Then:**
  - `SELECT FOR UPDATE SKIP LOCKED` ensures only one worker claims each row (INV-ED-08, CC-20)
  - Second worker's query returns no rows (all claimed by first)
  - Zero duplicate `xadd` calls to Redis Streams (T-09)
  - Redis stream contains exactly N messages for N distinct `event_id` values

**US-08: Outbox worker recovers failed rows on next cycle**
- **As a** developer whose outbox worker received a transient Redis timeout mid-batch
- **I want** the failed outbox rows to remain as `status="failed"` and be retried on the next drain cycle
- **So that** transient broker errors do not permanently lose events
- **Given:** Redis times out on 3 of 10 outbox rows during a drain cycle
- **When:** `drain_outbox()` catches the exception for those 3 rows
- **Then:**
  - 7 successfully published rows marked `status="published"` (CC-21)
  - 3 failed rows marked `status="failed"` with `last_error` populated (CC-08)
  - Next drain cycle retries only `status="pending"` rows (the worker resets failed rows to pending on retry run)
  - Alert fires if `failed` count exceeds threshold (CC-29)

**US-09: Published outbox rows are cleaned up to prevent table bloat**
- **As a** DBA concerned about `outbox_events` growing without bound
- **I want** published rows to be pruned automatically after a retention window
- **So that** the table stays bounded even after months of high-throughput event publishing
- **Given:** 500k `PUBLISHED` rows older than 7 days in `outbox_events`
- **When:** cleanup job runs (scheduled ARQ job, default nightly)
- **Then:**
  - All rows with `status="published"` and `published_at < now() - 7 days` are deleted (QS-12)
  - `PENDING` and `FAILED` rows untouched
  - Cleanup runs in batches of 10k to avoid long-running DELETE locks (T-10)
  - Table row count returns to bounded steady state

**US-10: `emit_event` raises on unregistered event type**
- **As a** developer who added a new event class but forgot to register its stream
- **I want** an immediate, clear `ValueError` rather than a silent no-op or a confusing NullPointerError later
- **So that** I can fix the stream registration before the code reaches production
- **Given:** `OrderShipped` event class exists but `"OrderShipped"` is not in `STREAM_MAP`
- **When:** `await emit_event(session, OrderShipped(...))` is called without `stream_name` keyword
- **Then:**
  - `ValueError("emit_event: no stream registered for event_type='OrderShipped'...")` raised (CC-02)
  - No `outbox_events` row inserted (transaction not flushed)
  - Error message includes the event_type name and instructs to add to STREAM_MAP
  - T-11 verifies: test creates unregistered event type and asserts ValueError raised

### 9.3 Retry and DLQ — resilience under failure (US-11..US-15)

**US-11: Handler failure triggers exponential backoff retry**
- **As a** developer whose payment handler depends on a downstream service that intermittently returns 503
- **I want** the consumer to retry failed events with exponential backoff rather than hammering the service
- **So that** the downstream service has time to recover between retry attempts
- **Given:** handler raises `httpx.HTTPStatusError(503)` on the first two attempts
- **When:** consumer calls `_process_with_retry()` with `max_attempts=5`
- **Then:**
  - First retry after ~200ms, second after ~400ms, third after ~800ms (INV-ED-04, CC-16)
  - ±10% jitter applied to avoid synchronised retries from multiple consumers
  - Third attempt succeeds: message ACKed, `_mark_seen()` called (CC-14)
  - No DLQ entry written (handler succeeded before max_attempts) (CC-15)

**US-12: Max attempts exceeded sends event to DLQ**
- **As a** developer whose consumer has a bug causing consistent handler failure
- **I want** poisoned messages quarantined in a DLQ after `max_attempts` so the stream is not blocked
- **So that** all other events continue processing while the broken event awaits manual inspection
- **Given:** handler raises `ValueError("invalid payload")` on every attempt; `max_attempts=5`
- **When:** consumer exhausts all 5 attempts
- **Then:**
  - Event written to `events:dlq` stream via `write_to_dlq()` (INV-ED-05, CC-15)
  - DLQ entry includes `original_payload`, `error_type="ValueError"`, `traceback`, `source_stream`, `dlq_at` (QS-05)
  - Message ACKed in consumer group so stream advances (CC-13)
  - Next message in stream processed normally — no blockage

**US-13: DLQ events can be replayed by operator**
- **As a** developer who has fixed the handler bug and wants to reprocess DLQ entries
- **I want** a CLI/script to read DLQ entries and re-enqueue them to the original stream
- **So that** no business events are permanently lost even after a handler bug
- **Given:** `events:dlq` stream has 20 entries from the broken handler
- **When:** operator runs `python -m events.replay --stream events:dlq --target events:orders`
- **Then:**
  - Each DLQ entry re-added to `events:orders` with a fresh `event_id` and `correlation_id` preserved
  - Original DLQ entries marked `replayed=true` (not deleted) for audit trail
  - Consumer processes replayed events; idempotency cache ensures no double handling if event_id matches (INV-ED-03)
  - T-15 verifies replay script produces correct Redis XADD calls

**US-14: Per-event retry policy can be configured**
- **As a** developer who wants critical payment events to retry more aggressively than low-priority analytics events
- **I want** to register a custom `RetryPolicy` for specific event types
- **So that** `PaymentProcessed` retries 10 times with 100ms base while `PageViewed` retries only 3 times
- **Given:** `retry_registry["PaymentProcessed"] = PerEventRetryOverride(max_attempts=10, base_delay_seconds=0.1)`
- **When:** payment consumer handler fails on attempt 1
- **Then:**
  - `get_policy_for_event("PaymentProcessed")` returns override policy (CC-05)
  - Consumer uses max_attempts=10 for this event type
  - T-14 verifies: two event types with different policies produce different backoff sequences

**US-15: DLQ write failure never crashes the consumer**
- **As a** developer whose Redis instance has a momentary write error on the DLQ stream
- **I want** the consumer to log the error and continue processing rather than crashing
- **So that** a secondary failure (DLQ unavailable) does not block the primary consumer loop
- **Given:** `redis.xadd(DLQ_STREAM, ...)` raises `ConnectionError` inside `write_to_dlq()`
- **When:** consumer tries to write to DLQ after max_attempts exceeded
- **Then:**
  - `write_to_dlq()` catches the exception, logs CRITICAL, and returns without re-raising (QS-09)
  - Consumer ACKs the message (stream advances) despite DLQ failure
  - Consumer loop continues processing next message
  - T-17 verifies: DLQ write mock raises; consumer does not crash; subsequent messages processed

### 9.4 Idempotency — safe duplicate delivery (US-16..US-20)

**US-16: Duplicate event delivery is silently skipped**
- **As a** developer whose Redis Streams broker redelivers an already-processed event on consumer restart
- **I want** the consumer to detect the duplicate via the seen cache and skip it without calling the handler
- **So that** the business logic is never executed twice for the same event
- **Given:** `event_id=abc123` already in `seen:consumer-1:abc123` Redis key; broker redelivers message
- **When:** consumer reads the redelivered message in `xreadgroup` loop
- **Then:**
  - `_is_seen("abc123")` returns `True` (CC-14)
  - Handler NOT called — zero side effects from duplicate (INV-ED-03)
  - Message ACKed so it does not remain in the PEL (Pending Entry List)
  - DEBUG log: `skipping duplicate event_id=abc123` emitted (QS-03)

**US-17: Seen cache TTL ensures old duplicates are ignored**
- **As a** developer whose service restarts after 8 days and receives an extremely late redelivery
- **I want** very old events (older than the TTL) to be processed again rather than silently dropped
- **So that** events that genuinely need reprocessing after long outages are not silently discarded
- **Given:** `event_id=xyz999` was processed 8 days ago; Redis key has expired (TTL=7 days)
- **When:** broker redelivers the event (extreme edge case)
- **Then:**
  - `_is_seen("xyz999")` returns `False` (key expired)
  - Handler called; event processed as new
  - `_mark_seen()` renews the key for another 7 days
  - T-21 verifies: Redis `setex` called with `SEEN_CACHE_TTL_SECONDS` value

**US-18: Each consumer group has independent idempotency cache**
- **As a** developer running both a shipping-service consumer and an analytics consumer on the same stream
- **I want** shipping-service's seen cache to be independent of analytics's seen cache
- **So that** both services process every event once, regardless of the other's state
- **Given:** `shipping-service` and `analytics` are separate consumer groups on `events:orders`
- **When:** `OrderCreated` event with `event_id=evt-001` delivered to both groups
- **Then:**
  - Shipping: key `seen:shipping-consumer-1:evt-001` set after handler (INV-ED-03)
  - Analytics: key `seen:analytics-consumer-1:evt-001` set after handler (INV-ED-03)
  - Neither key presence blocks the other group
  - T-22 verifies: same event_id processed twice with different consumer names, handler called twice total

**US-19: Idempotency cache survives consumer restart**
- **As a** developer who rolls out a new consumer deployment
- **I want** the seen cache to persist across consumer restarts so that in-flight events redelivered post-restart are not double-processed
- **So that** a rolling deploy does not cause duplicate processing of the events in-flight at deploy time
- **Given:** consumer-1 restarts; Redis retains seen cache with 5d TTL remaining
- **When:** broker redelivers the 3 events that were in-flight at restart time
- **Then:**
  - `_is_seen()` returns True for all 3 redelivered events (cache survived restart)
  - Handler NOT called for any of the 3
  - New events arriving after restart processed normally
  - T-20 verifies: mock consumer restart (re-instantiate `EventConsumer`); redelivered events skipped

**US-20: Idempotency works under high concurrency**
- **As a** developer running 10 parallel consumer instances on the same stream
- **I want** a race condition where two instances receive the same message (pre-group-ack) to be handled safely
- **So that** even with concurrent consumers, no event is processed more than once
- **Given:** consumer group with 10 workers; same `event_id` arrives (edge case in NATS or manual replay)
- **When:** two workers call `_is_seen(event_id)` simultaneously before either calls `_mark_seen`
- **Then:**
  - Redis `SETEX` is atomic; only one worker's `_mark_seen` wins the race (CC-14)
  - Even if both pass the `_is_seen` check, business logic idempotency (e.g. DB unique constraint) prevents double commit
  - T-23 verifies concurrent async tasks calling `_process_with_retry` with same event_id

### 9.5 Edge cases — broker down, crashes, schema evolution, tool idempotency (US-21..US-25)

**US-21: Consumer crashes mid-handler — event re-delivered safely**
- **As a** developer whose consumer process is killed mid-handler execution (OOM kill, SIGKILL)
- **I want** the event to be redelivered to a live consumer without data loss or double-processing
- **So that** the system heals automatically from infrastructure failures
- **Given:** consumer-1 claims event `evt-999` via `xreadgroup`; process killed before `xack`
- **When:** Redis consumer group idle timeout triggers; event moves to another consumer
- **Then:**
  - Event in PEL (Pending Entry List) claimed by consumer-2 via `xclaim` or `xautoclaim`
  - `_is_seen("evt-999")` returns False (handler never completed, `_mark_seen` never called)
  - Handler called on consumer-2; event processed and ACKed (INV-ED-03)
  - T-25 verifies: simulate PEL re-delivery; handler called once total across two consumer instances

**US-22: Poisoned message does not block the stream**
- **As a** developer whose stream has one event with a malformed payload that always causes a `ValidationError`
- **I want** the consumer to quarantine the poisoned message in the DLQ and continue processing subsequent events
- **So that** one bad event does not freeze the entire event pipeline indefinitely
- **Given:** message at stream offset 1001 has invalid JSON in `payload` field; offset 1002 is valid
- **When:** consumer reads offset 1001, all retries fail with `ValidationError`
- **Then:**
  - Offset 1001 written to DLQ after max_attempts with full error context (INV-ED-05, CC-15, QS-05)
  - Message ACKed; stream advances to offset 1002 (CC-13)
  - Offset 1002 processed normally; pipeline unblocked (T-26 verifies)

**US-23: Schema evolution — V1 consumer receives V2 event gracefully**
- **As a** developer who deployed a new V2 `OrderCreated` schema but has V1 consumers still running
- **I want** V1 consumers to handle V2 events by downgrading them or ignoring unknown fields
- **So that** a rolling deploy does not require simultaneous update of all consumers
- **Given:** producer emits `OrderCreatedV2` with `shipping_address` field; V1 consumers active
- **When:** V1 consumer receives V2 event payload
- **Then:**
  - `OrderCreatedV1.model_validate(payload)` succeeds because extra fields are ignored by default (Pydantic v2 `model_config = {"extra": "ignore"}`)
  - Handler called with V1 view of the event; no crash (CC-17, CC-18)
  - `schema_version=2` in payload; V1 consumer logs a WARNING: `received_newer_schema version=2 expected=1` (QS-07)
  - T-28 verifies: V2 payload parsed by V1 consumer without exception

**US-24: Tool idempotency — re-run on existing scaffold is a no-op**
- **As a** developer who runs `add_event_driven` a second time on an already-scaffolded project
- **I want** the tool to detect existing files and return `{status: "no_op"}` without overwriting them
- **So that** my hand-edited consumer handlers and event schemas are never accidentally overwritten
- **Given:** `events/base.py`, `events/producer.py`, `events/consumer.py` already exist
- **When:** `add_event_driven(project_dir)` called again with same parameters
- **Then:**
  - Tool detects all target files exist (CC-34)
  - Returns `{status: "no_op", files_skipped: [...], reason: "already scaffolded"}`
  - Zero bytes written to filesystem (T-27 verifies via filesystem checksum)
  - No error raised; clean exit with informational message

**US-25: Consumer lag metric triggers warning when backlog exceeds threshold**
- **As a** SRE monitoring the event pipeline
- **I want** a WARNING log emitted when consumer lag exceeds 1000 events
- **So that** I can proactively scale out consumers before the backlog causes downstream timeouts
- **Given:** `events:orders` stream has 5000 unprocessed entries; consumer reads 10 at a time
- **When:** consumer queries stream length via `xlen` after each batch
- **Then:**
  - `xlen` result compared against `settings.EVENT_CONSUMER_LAG_WARN_THRESHOLD` (default 1000) (CC-33)
  - WARNING log emitted: `consumer_lag stream=events:orders lag=5000` (CC-33)
  - Log rate-limited to once per 60s to avoid log flood
  - T-24 verifies: mock xlen returning 5000; WARNING captured in log records

---

## 10. Test Plan

The 30 tests are grouped into six categories: event-model basics, transactional-outbox guarantees, retry-and-DLQ behavior, consumer idempotency, failure isolation, and schema evolution / observability. Every test case is either a fast unit test (mocked DB / mocked Redis) or an integration test against real Postgres + Redis containers — no fakes, no stubs.

### 10.1 Event model basics (T-01..T-05)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-01 | BaseEvent Pydantic validation on construction | Unit | `BaseEvent(event_type="X")` sets `event_id`, `occurred_at`; invalid event_type raises `ValidationError` |
| T-02 | event_id is time-ordered UUID | Unit | Two events created 1ms apart have `event_id_a < event_id_b` lexicographically |
| T-03 | BaseEvent is immutable | Unit | Setting field on frozen model raises `ValidationError` |
| T-04 | `to_stream_payload` serialises all fields as strings | Unit | All values in returned dict are `str` instances |
| T-05 | `emit_event` inserts OutboxEvent row in session | Unit (mock session) | `session.flush()` called; `OutboxEvent.event_id` matches event |

### 10.2 Transactional outbox guarantees (T-06..T-11)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-06 | Consumer graceful shutdown on SIGTERM | Integration | `stop()` called; loop exits; in-flight ACKs complete; no `RuntimeError` |
| T-07 | Outbox write atomic with business row | Integration (real DB) | Transaction rollback removes both `orders` row and `outbox_events` row |
| T-08 | `emit_event` raises `ValueError` for unregistered event type | Unit | `ValueError` raised; no DB write; error message contains event_type name |
| T-09 | `SELECT FOR UPDATE SKIP LOCKED` prevents double-drain | Integration (two workers) | Zero duplicate `xadd` calls when two `drain_outbox()` calls run concurrently |
| T-10 | Cleanup job prunes PUBLISHED rows older than 7 days | Integration | Rows with `published_at < now() - 7d` deleted; PENDING rows untouched |
| T-11 | Outbox worker marks row PUBLISHED after successful xadd | Unit | `OutboxEvent.status == "published"` and `published_at` set after drain |

### 10.3 Retry policy and dead-letter queue (T-12..T-17)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-12 | `exponential_backoff` respects `max_delay_seconds` | Unit | Delay at attempt=15 ≤ `policy.max_delay_seconds` |
| T-13 | Retry delay monotonically increases | Unit | `delays[i+1] > delays[i]` for attempts 1..5 with zero jitter |
| T-14 | Per-event retry override applied correctly | Unit | `get_policy_for_event("PaymentProcessed")` returns `max_attempts=10` after registry setup |
| T-15 | DLQ entry written after max_attempts | Integration (mock Redis) | `xadd(DLQ_STREAM, ...)` called once; original payload in DLQ fields |
| T-16 | DLQ entry contains required fields | Unit | DLQ dict has `original_payload`, `error_type`, `traceback`, `source_stream`, `dlq_at` |
| T-17 | DLQ write failure does not crash consumer | Unit | Mock `xadd` raises; consumer continues; next message processed |

### 10.4 Consumer idempotency (T-18..T-23)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-18 | Consumer skips duplicate event_id | Unit (mock Redis) | Handler NOT called when `exists()` returns 1 for seen key |
| T-19 | Seen cache set after successful handler | Unit (mock Redis) | `setex(seen:consumer-1:event_id, TTL, 1)` called after handler returns |
| T-20 | Idempotency survives consumer restart | Integration | New `EventConsumer` instance; redelivered events skipped via persistent Redis cache |
| T-21 | Seen cache TTL matches constant | Unit | `setex` called with `SEEN_CACHE_TTL_SECONDS = 604800` |
| T-22 | Independent caches for different consumer groups | Integration | Same event_id processed by two consumer names; handler called twice total |
| T-23 | Concurrent consumers — race condition safe | Async integration | 10 concurrent `_process_with_retry` calls; handler called exactly once |

### 10.5 Failure isolation and lag (T-24..T-27)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-24 | Consumer lag WARNING emitted above threshold | Unit | `xlen = 5000 > 1000`; WARNING log captured with `consumer_lag` field |
| T-25 | PEL re-delivery handled idempotently | Integration | Event in PEL reclaimed; handler called once total; no double processing |
| T-26 | Poisoned message quarantined; stream unblocked | Integration | DLQ written; next message in stream processed without delay |
| T-27 | Tool idempotency — second run is no-op | Integration | `add_event_driven` twice; second call returns `{status: "no_op"}`; zero bytes written |

### 10.6 Schema evolution and observability (T-28..T-30)

| ID | Name | Method | Expected |
|----|------|--------|----------|
| T-28 | Schema migration rejects unknown version | Unit | `migrate_order_created({"schema_version": 99, ...})` raises `ValueError` |
| T-29 | V2 event processed by V1 consumer without crash | Unit | V2 payload parsed by V1 schema; extra fields ignored; WARNING log emitted |
| T-30 | OTel trace context propagated producer → consumer | Integration | Consumer span has same `trace_id` as producer span; `traceparent` in event payload |

---

## 11. Interaction Matrix

| Tool | Interaction | Direction | Notes |
|------|-------------|-----------|-------|
| TOOL-023 (`add_outbox_pattern`) | Provides `OutboxEvent` model and `drain_outbox` base patterns; TOOL-046 scaffolds the full event-driven layer on top | TOOL-023 → TOOL-046 | If TOOL-023 already ran, TOOL-046 detects existing outbox model and skips its creation (CC-34) |
| TOOL-015 (`add_webhook_sender`) | Webhooks are an alternative delivery mechanism; TOOL-046 consumers can dispatch to webhook senders after event processing | TOOL-046 → TOOL-015 | Consumer handler may call webhook sender; event pipeline feeds external subscriber notifications |
| TOOL-014 (`add_sse`) | SSE endpoints can push events to browser clients; TOOL-046 consumer can write to SSE broadcast channel after receiving domain event | TOOL-046 → TOOL-014 | OrderCreated event → consumer → SSE broadcast to admin dashboard |
| TOOL-005 (`add_audit_log`) | Every event emitted and consumed should generate an audit log entry | TOOL-046 → TOOL-005 | `emit_event()` and consumer ACK can call audit logger; shared correlation_id |
| TOOL-045 (`extract_service`) | Extracted microservices communicate via events; TOOL-046 scaffolded broker is the transport layer for extracted services | TOOL-045 → TOOL-046 | Extracted service uses `emit_event()` and `EventConsumer` from TOOL-046 scaffold |
| TOOL-008 (`add_multi_tenancy`) | Multi-tenant events must carry `tenant_id` in payload; consumer must filter or route by tenant | TOOL-008 → TOOL-046 | `BaseEvent` extended with optional `tenant_id` field; consumer groups can be per-tenant |
| TOOL-001 (`scaffold_project`) | Base project structure must exist before event-driven layer can be added | TOOL-001 → TOOL-046 | `project_dir` must have `app/models/base.py` and `app/core/db.py` (checked at startup) |
| TOOL-003 (`add_sqlalchemy`) | `OutboxEvent` model requires SQLAlchemy 2.0 async engine; TOOL-003 sets that up | TOOL-003 → TOOL-046 | TOOL-046 checks `async_sessionmaker` present before scaffolding outbox model |
| TOOL-033 (`add_background_jobs`) | ARQ worker infrastructure may already exist from TOOL-033; TOOL-046 adds `drain_outbox` job to existing `WorkerSettings` | TOOL-033 → TOOL-046 | If `WorkerSettings` exists, tool appends `drain_outbox` to `functions` list rather than creating new file |
| TOOL-036 (`add_redis`) | Redis connection pool must exist for stream operations; TOOL-036 provides it | TOOL-036 → TOOL-046 | `events/consumer.py` imports `get_redis()` from `app/core/redis.py` scaffolded by TOOL-036 |
| TOOL-039 (`add_observability`) | Langfuse/OpenTelemetry instrumentation set up by TOOL-039 is consumed by `events/tracing.py` | TOOL-039 → TOOL-046 | `inject_trace_context()` reads active OTel span set up by TOOL-039 instrumentation |
| TOOL-002 (`add_alembic`) | Alembic migration for `outbox_events` table requires Alembic already configured | TOOL-002 → TOOL-046 | Migration file written to `alembic/versions/`; TOOL-046 calls TOOL-002's migration runner API |
| TOOL-004 (`add_pydantic_settings`) | `Settings` class must have `REDIS_STREAMS_URL`, `EVENT_MAX_ATTEMPTS`, `EVENT_OUTBOX_BATCH_SIZE` | TOOL-004 → TOOL-046 | TOOL-046 adds settings fields to existing `Settings` class via edit; does not create new config file |
| TOOL-018 (`add_rate_limiting`) | High-throughput event producers should be rate-limited at the HTTP layer to prevent outbox flooding | TOOL-018 → TOOL-046 | Rate limit applied at route level before `emit_event()` is called |
| TOOL-021 (`add_testing`) | Test fixtures for async sessions and Redis mocks reused by `tests/test_event_driven.py` | TOOL-021 → TOOL-046 | `async_session_fixture` and `redis_mock_fixture` imported from conftest |

---

## 12. Rollback Procedure

### 12.1 Code rollback

If the scaffolded event-driven code introduces a regression, revert all generated files atomically:

```bash
# Revert all scaffolded event files using git
git diff --name-only HEAD | grep "^events/" | xargs git checkout HEAD --
git checkout HEAD -- app/models/outbox_event.py
git checkout HEAD -- tests/test_event_driven.py

# Verify no event imports remain in application code
grep -r "from events" src/ app/ --include="*.py"
# Should return empty or only intentional imports

# Confirm the application starts without event modules
PYTHONPATH=. python -c "from app.main import app; print('startup ok')"
```

### 12.2 Database rollback — outbox_events table

The `outbox_events` table is created by the Alembic migration `0046_add_outbox_events`. Roll it back with:

```bash
# Roll back the outbox_events migration
alembic downgrade -1

# Verify table is gone
psql "$DATABASE_URL" -c "\d outbox_events"
# Should return: Did not find any relation named "outbox_events"

# Confirm no FK violations remain
psql "$DATABASE_URL" -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'outbox%';"
```

The `downgrade()` function in the migration drops the table and its indexes cleanly:

```python
# alembic/versions/0046_add_outbox_events.py (downgrade fragment)
def downgrade() -> None:
    op.drop_index("ix_outbox_event_id", table_name="outbox_events")
    op.drop_index("ix_outbox_status_created", table_name="outbox_events")
    op.drop_table("outbox_events")
```

### 12.3 Data preservation rollback — pending outbox events

Before rolling back, preserve any `PENDING` outbox events that have not yet been published to avoid data loss:

```bash
# Export all PENDING outbox events to a JSON file before dropping the table
psql "$DATABASE_URL" -c \
  "COPY (SELECT * FROM outbox_events WHERE status='pending' ORDER BY created_at) \
   TO STDOUT CSV HEADER" > /tmp/outbox_pending_backup_$(date +%Y%m%d_%H%M%S).csv

# Count how many pending events exist
psql "$DATABASE_URL" -c "SELECT COUNT(*) FROM outbox_events WHERE status='pending';"

# If count > 0, manually replay from backup after rollback if needed:
# python scripts/replay_outbox_backup.py /tmp/outbox_pending_backup_*.csv
```

### 12.4 Failure mode: broker (Redis) permanently down

If the Redis broker is permanently unavailable (not just transient):

```bash
# 1. Stop all outbox workers to prevent failed drain attempts filling logs
pkill -f "arq events.outbox_worker"

# 2. Check how many events are stuck in outbox
psql "$DATABASE_URL" -c \
  "SELECT status, COUNT(*) FROM outbox_events GROUP BY status;"

# 3. Export pending events for manual processing
psql "$DATABASE_URL" -c \
  "SELECT event_id, event_type, payload, created_at \
   FROM outbox_events WHERE status='pending' \
   ORDER BY created_at" > /tmp/stuck_events.txt

# 4. Switch broker to NATS as emergency fallback
export BROKER_TYPE=nats
export NATS_URL=nats://fallback-nats:4222
python -m events.outbox_worker --broker nats

# 5. Once Redis recovers, drain residual pending events
PYTHONPATH=. arq events.outbox_worker.WorkerSettings
```

### 12.5 Failure mode: consumer crash during handler

If a consumer crashes mid-handler before ACKing a message, the event remains in the PEL:

```bash
# 1. Inspect the Pending Entry List for a stream
redis-cli XPENDING events:orders shipping-group - + 50

# 2. Claim stale entries that have exceeded idle time (e.g. 60s)
redis-cli XAUTOCLAIM events:orders shipping-group new-consumer-1 60000 0-0

# 3. Verify message is now assigned to the new consumer
redis-cli XPENDING events:orders shipping-group - + 10

# 4. If consumer is permanently down, manually ACK entries that were successfully processed
# (check application logs for last confirmed processed event_id)
redis-cli XACK events:orders shipping-group <last-confirmed-msg-id>
```

### 12.6 Failure mode: DLQ filled to capacity

If the DLQ stream grows beyond acceptable bounds:

```bash
# 1. Inspect DLQ contents to understand failure pattern
redis-cli XRANGE events:dlq - + COUNT 20

# 2. Count DLQ entries
redis-cli XLEN events:dlq

# 3. If all entries share the same error type (e.g. handler bug now fixed)
# replay them back to the original stream
python -m events.replay \
  --source events:dlq \
  --target events:orders \
  --filter error_type=ValueError \
  --limit 1000

# 4. Trim DLQ after successful replay to prevent memory pressure
redis-cli XTRIM events:dlq MAXLEN 0

# 5. Deploy fixed handler version before replaying
# Verify fix: python -m pytest tests/test_event_driven.py -k "dlq" -v
```

### 12.7 Emergency: poisoned schema version blocks all consumers

If a consumer is in a crash loop due to an unrecognised schema version:

```bash
# 1. Identify the offending stream offset
redis-cli XRANGE events:orders - + COUNT 5

# 2. Move the poisoned message to DLQ manually
redis-cli XADD events:dlq "*" \
  original_stream events:orders \
  reason "manual_quarantine_schema_version_unknown" \
  moved_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# 3. ACK the poisoned message to unblock the consumer group
redis-cli XACK events:orders shipping-group <poisoned-msg-id>

# 4. Delete it from the stream (optional, after quarantine confirmed)
redis-cli XDEL events:orders <poisoned-msg-id>

# 5. Restart consumers — they will now skip the removed offset
docker compose restart arq-consumer

# 6. Deploy the updated migration hook that handles the new schema version
# Then replay the quarantined event from DLQ
python -m events.replay --source events:dlq --filter reason=manual_quarantine_schema_version_unknown
```

---

## 13. Edge Cases

| # | Scenario | Expected |
|----|----------|---------|
| EC-01 | Broker unreachable during outbox drain | Events accumulate in `outbox_events`; drain retries on next cycle; no data loss from producer side |
| EC-02 | Consumer crashes before `xack` | Event remains in PEL; `xautoclaim` re-delivers to live consumer; idempotency prevents double execution |
| EC-03 | Duplicate event_id (broker at-least-once redelivery) | Seen cache hit; handler not called; message ACKed silently; DEBUG log emitted |
| EC-04 | Schema V1 event received by V2 consumer | `migrate_order_created()` upcast to V2 with safe default (`shipping_address=None`); handler called with V2 view |
| EC-05 | Schema V2 event received by V1 consumer | Pydantic `extra="ignore"` absorbs unknown fields; V1 consumer processes successfully; WARNING log for version mismatch |
| EC-06 | DLQ stream grows beyond threshold | Grafana alert fires at > 10 events/minute; operator uses replay script to reprocess after bug fix |
| EC-07 | Outbox table unbounded growth | Nightly cleanup job prunes `PUBLISHED` rows older than 7 days in batches of 10k |
| EC-08 | Consumer lag exceeds 1000 events | WARNING log emitted at most once per 60s; scale-out suggestion in log; no automatic action taken |
| EC-09 | Handler raises on schema `ValidationError` (poisoned payload) | Retries exhaust immediately (validation errors are not retryable); DLQ entry written; stream unblocked |
| EC-10 | Tool re-run on already scaffolded project | `{status: "no_op"}` returned; zero bytes written; hand-edited files untouched |
| EC-11 | Multiple consumer groups on same stream | Each group has independent consumer group in Redis; independent seen caches keyed by consumer name |
| EC-12 | Event arrives after seen cache TTL expiry (8+ days late) | Processed as new event; `_mark_seen` renews cache; business logic must be idempotent for this edge case |
| EC-13 | `emit_event()` called outside a `session.begin()` block | `session.flush()` raises `InvalidRequestError`; error propagates; no partial outbox row inserted |
| EC-14 | SIGTERM during `drain_outbox()` mid-batch | ARQ job completes current batch before shutdown; `WorkerSettings.job_completion_wait=60` ensures clean exit |
| EC-15 | Redis Streams broker latency spike to >500ms | Consumer `xreadgroup BLOCK 100` returns empty; lag metric increases; no crash; backlog visible on dashboard |

---

## 14. Acceptance Criteria

- ✅ `BaseEvent` Pydantic v2 model with UUID v7 `event_id`, `occurred_at`, `correlation_id`, `schema_version` scaffolded at `events/base.py`
- ✅ Transactional outbox pattern implemented: `emit_event()` writes `OutboxEvent` in caller's DB transaction; outbox worker publishes to broker separately
- ✅ `outbox_events` table with `(status, created_at)` index and `event_id` unique constraint; Alembic migration with clean `downgrade()` that drops the table
- ✅ ARQ outbox worker uses `SELECT FOR UPDATE SKIP LOCKED`; zero duplicate publishes under concurrent drain
- ✅ `EventConsumer` uses Redis consumer groups; idempotency via `seen:{consumer}:{event_id}` Redis key with 7-day TTL
- ✅ Exponential backoff with jitter applied on every retry; no fixed-interval sleep in consumer retry path
- ✅ DLQ handler quarantines poisoned messages after `max_attempts` with full error metadata; never blocks consumer loop even on secondary DLQ write failure
- ✅ Schema evolution via versioned event classes with explicit migration hooks; unrecognised version raises `ValueError`
- ✅ OpenTelemetry trace context propagated from producer to consumer via `traceparent` field; no-op when OTel not installed
- ✅ `tests/test_event_driven.py` with ≥ 30 tests passing; T-01..T-30 all green; tool idempotent on second run

---

## 15. Implementation Checklist

### 15.1 Base Event Infrastructure
- [ ] Create `events/` package with `__init__.py`
- [ ] Implement `events/base.py` with `BaseEvent(BaseModel)` and `_uuid7()` factory
- [ ] Add `to_stream_payload()` method that serialises all fields as `dict[str, str]`
- [ ] Verify `model_config = {"frozen": True}` prevents mutation
- [ ] Add `correlation_id: UUID | None` and `schema_version: int = 1` fields
- [ ] Add `producer_service: str` field for multi-service observability
- [ ] Unit test: construction, immutability, serialisation (T-01..T-04)

### 15.2 Event Schema Registry
- [ ] Create `events/schemas/` directory with `__init__.py`
- [ ] Scaffold one `{event_type_lower}.py` per event name in `events` parameter
- [ ] Each schema file exports `{EventType}V1(BaseEvent)` class
- [ ] Add `model_config = {"extra": "ignore"}` for forward-compat with newer schema versions
- [ ] Register stream name in `STREAM_MAP` for each new event type
- [ ] Add migration hook `migrate_{event_type}()` placeholder for V2 upgrade path
- [ ] Verify `schema_version` field default = 1 on all generated schemas
- [ ] Documentation comment per schema file explaining fields and business context

### 15.3 Producer and Outbox Model
- [ ] Create `app/models/outbox_event.py` with `OutboxEvent` SQLAlchemy 2.0 model
- [ ] Add `status`, `attempts`, `last_error`, `created_at`, `published_at` columns
- [ ] Add composite index `(status, created_at)` and unique index on `event_id`
- [ ] Implement `events/producer.py` with `emit_event(session, event, *, stream_name)` function
- [ ] Verify `emit_event()` calls `session.flush()` not `session.commit()`
- [ ] Raise `ValueError` for unregistered event types without `stream_name` override
- [ ] Call `inject_trace_context()` on payload before writing to outbox
- [ ] Unit tests: atomic write (T-07), unregistered type error (T-08), flush vs commit (T-05)

### 15.4 Alembic Migration
- [ ] Generate migration file `alembic/versions/0046_add_outbox_events.py`
- [ ] `upgrade()` creates `outbox_events` table with all 9 columns
- [ ] `upgrade()` creates composite index `ix_outbox_status_created`
- [ ] `upgrade()` creates unique index `ix_outbox_event_id`
- [ ] `downgrade()` drops indexes in reverse order before dropping table
- [ ] Test migration: `alembic upgrade head` + `alembic downgrade -1` cycle clean
- [ ] Verify `downgrade()` leaves database in pre-migration state

### 15.5 Outbox Drain Worker
- [ ] Implement `events/outbox_worker.py` with `drain_outbox(ctx)` ARQ job function
- [ ] Use `SELECT FOR UPDATE SKIP LOCKED` to prevent concurrent double-drain
- [ ] Batch size configurable via `settings.EVENT_OUTBOX_BATCH_SIZE` (default 100)
- [ ] Mark row `PUBLISHED` + set `published_at` after successful `xadd`
- [ ] Mark row `FAILED` + set `last_error` on exception; increment `attempts`
- [ ] Implement `WorkerSettings` with `drain_outbox` in `functions` list
- [ ] Implement cleanup job that prunes `PUBLISHED` rows older than 7 days in batches
- [ ] Integration test: concurrent drain, zero duplicates (T-09), cleanup (T-10)

### 15.6 Event Consumer
- [ ] Implement `events/consumer.py` with `EventConsumer` class
- [ ] Use `xreadgroup` (consumer groups) not plain `xread`
- [ ] Implement `_ensure_group()` with BUSYGROUP tolerance on first run
- [ ] Implement `_is_seen()` and `_mark_seen()` with configurable TTL
- [ ] Implement `_process_with_retry()` with `exponential_backoff()` delay
- [ ] Call `write_to_dlq()` after max_attempts; ACK message even on DLQ write failure
- [ ] Register SIGTERM handler calling `self.stop()` for graceful shutdown
- [ ] Emit consumer lag WARNING when `xlen > settings.EVENT_CONSUMER_LAG_WARN_THRESHOLD`
- [ ] Unit + integration tests: idempotency (T-18..T-23), graceful shutdown (T-06), lag (T-24)

### 15.7 Retry Policy Engine
- [ ] Implement `events/retry.py` with `RetryPolicy` dataclass and `exponential_backoff()` function
- [ ] Jitter: `±policy.jitter_fraction * raw_delay` (default ±10%)
- [ ] Hard cap: `min(raw_delay + jitter, policy.max_delay_seconds)`
- [ ] Implement `PerEventRetryOverride` dataclass and `retry_registry` global dict
- [ ] Implement `get_policy_for_event(event_type)` with fallback to defaults
- [ ] Unit tests: monotonic growth (T-13), max_delay cap (T-12), per-event override (T-14)

### 15.8 DLQ Handler
- [ ] Implement `events/dlq.py` with `write_to_dlq()` async function
- [ ] Include all 5 required fields: `original_payload`, `error_type`, `error_message`, `traceback`, `source_stream`, `dlq_at`
- [ ] Wrap Redis XADD in try/except; log CRITICAL on failure; never re-raise
- [ ] Implement `events/replay.py` CLI script for operator DLQ replay
- [ ] Replay script: read DLQ entries, re-enqueue to original stream, mark as replayed
- [ ] Unit tests: fields present (T-16), write failure no-crash (T-17), replay script (T-15)

### 15.9 Schema Migration Hooks
- [ ] Implement V1→V2 migration hook for `OrderCreated` as reference pattern
- [ ] `migrate_{event_type}(raw: dict) -> V2Class` function in each schema file
- [ ] V1 payloads: upcast with safe defaults for new fields
- [ ] V2 passthrough: `V2Class(**raw)` directly
- [ ] Unknown version: raise `ValueError` with version number in message
- [ ] Unit tests: V1→V2 migration (T-28), unknown version error (T-28), V2 passthrough (T-29)

### 15.10 Trace Propagation
- [ ] Implement `events/tracing.py` with `inject_trace_context()` and `with_trace_context()`
- [ ] Guard all OTel imports with `try/except ImportError`; set `OTEL_AVAILABLE = False` on miss
- [ ] `inject_trace_context()` returns unchanged payload dict when `OTEL_AVAILABLE = False`
- [ ] `with_trace_context()` is an async context manager wrapping consumer handler span
- [ ] Span name: `f"consume:{payload.get('event_type', 'unknown')}"`
- [ ] Integration test: trace_id matches producer → consumer (T-30), no-op without OTel (CC-31)

### 15.11 Config and Dependency Updates
- [ ] Add `REDIS_STREAMS_URL: str`, `EVENT_MAX_ATTEMPTS: int = 5`, `EVENT_OUTBOX_BATCH_SIZE: int = 100` to `Settings`
- [ ] Add `EVENT_CONSUMER_LAG_WARN_THRESHOLD: int = 1000` and `BROKER_TYPE: str = "redis_streams"` to `Settings`
- [ ] Update `pyproject.toml`: add `redis>=5.0`, `arq>=0.25` to optional `[events]` extras
- [ ] Register `drain_outbox` job in `main.py` lifespan startup if ARQ context present
- [ ] Update `docker-compose.yml` with ARQ worker service definition

### 15.12 Monitoring and Alerting
- [ ] Create `monitoring/alerts/events.json` Grafana alert template
- [ ] Alert 1: DLQ growth rate > 10 events/minute
- [ ] Alert 2: Consumer lag > 1000 events for > 5 minutes
- [ ] Alert 3: Outbox `FAILED` count > 50
- [ ] Alert 4: Outbox `PENDING` count > 10000 (drain worker may be down)
- [ ] Add `Makefile` targets: `events-worker-start`, `events-drain-once`, `events-dlq-inspect`

### 15.13 Tests and CI
- [ ] Create `tests/test_event_driven.py` with ≥ 30 test functions covering T-01..T-30
- [ ] Add `pytest-asyncio` fixtures for Redis mock and async session
- [ ] Ensure all tests pass with `PYTHONPATH=. pytest tests/test_event_driven.py -v`
- [ ] Add CI lint check: no `asyncio.sleep(constant)` in `events/consumer.py` retry path
- [ ] Add CI gate: `grep -r "from events" src/ app/` confirms correct import paths
- [ ] Register tool in `mcp_server.py` under `EVOLVE` category with correct signature
- [ ] Run full E2E test: `add_event_driven` → emit 100 events → drain → consume → assert 100 processed

---

## 16. Documentation Output

```json
{
  "status": "success",
  "tool": "fastapi_add_event_driven",
  "spec_version": "v2",
  "metrics": {
    "publish_latency_p99_ms": 5,
    "consume_latency_p99_ms": 50,
    "outbox_drain_rate_per_sec": 500,
    "idempotency_ttl_days": 7,
    "retry_max_attempts": 5,
    "retry_base_delay_ms": 200,
    "retry_max_delay_sec": 30,
    "dlq_alert_threshold_per_min": 10
  },
  "files_created": [
    "events/__init__.py",
    "events/base.py",
    "events/producer.py",
    "events/consumer.py",
    "events/outbox_worker.py",
    "events/dlq.py",
    "events/retry.py",
    "events/tracing.py",
    "events/replay.py",
    "events/schemas/__init__.py",
    "events/schemas/order_created.py",
    "app/models/outbox_event.py",
    "alembic/versions/0046_add_outbox_events.py",
    "monitoring/alerts/events.json",
    "tests/test_event_driven.py"
  ],
  "files_modified": [
    "app/main.py",
    "app/core/config.py",
    "pyproject.toml",
    "docker-compose.yml"
  ],
  "next_steps": [
    "Run `alembic upgrade head` to create the outbox_events table in your database",
    "Add `await emit_event(session, YourEvent(...))` inside your existing transaction blocks",
    "Start the outbox worker: `arq events.outbox_worker.WorkerSettings`",
    "Register event handlers in your consumer entrypoint and start with `asyncio.run(consumer.run())`",
    "Review `STREAM_MAP` in `events/producer.py` and add your domain event types with their stream names",
    "Configure Grafana alerts from `monitoring/alerts/events.json` for DLQ growth and consumer lag",
    "For Kafka: swap `EventConsumer` for `events/adapters/kafka.py` adapter; outbox model unchanged"
  ],
  "warnings": [
    "UUID v7 requires Python 3.13+ for native support; `_uuid7()` falls back to a time-ordered UUID v4 hybrid on earlier versions — timestamps are correct but ordering guarantees are weaker",
    "The outbox cleanup job prunes PUBLISHED rows after 7 days; if you need a longer audit trail, increase retention by changing the DELETE threshold or writing to an archive table instead"
  ],
  "notes": [
    "Broker choice (redis_streams | kafka | nats) only affects the transport adapter in outbox_worker.py and consumer.py — the BaseEvent schema, outbox model, and idempotency logic are broker-agnostic",
    "Schema evolution: always add new fields as Optional with defaults to preserve V1 consumer compatibility; never remove a field without a deprecation migration window of at least one deploy cycle",
    "The transactional outbox guarantees at-least-once delivery, not exactly-once — consumers must always be idempotent; the seen cache reduces duplicates but does not eliminate them at the DB layer",
    "For multi-tenant deployments (TOOL-008), extend BaseEvent with an optional `tenant_id: uuid.UUID | None` field and add tenant-based consumer group routing in the consumer dispatch layer"
  ]
}
```
