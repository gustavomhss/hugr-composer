# TOOL-023: add_outbox_pattern

> **Status**: SPEC v2 (rigorous)
> **Last updated**: 2026-04-08

---

## 1. Overview

| Property | Value |
|----------|-------|
| Tool name | `fastapi_add_outbox_pattern` |
| Category | EXTEND > Infrastructure |
| Complexity | High |
| Dependencies | FastAPI, SQLAlchemy, Alembic, ARQ |
| Signature | `add_outbox_pattern(project_dir: str, dispatcher_poll_seconds: float = 1.0, batch_size: int = 100, max_retries: int = 5, dispatch_targets: list[Literal["webhook","sse","kafka"]] = None) -> dict` |
| Parameters | `project_dir`: Absolute path to project root (e.g. `/app/project`)<br>`dispatcher_poll_seconds`: Worker poll interval (default: 1.0)<br>`batch_size`: Max events per poll cycle (default: 100)<br>`max_retries`: Max dispatch attempts per event (default: 5)<br>`dispatch_targets`: Enabled delivery targets (default: ["webhook"]) |

## 2. Purpose

The `fastapi_add_outbox_pattern` tool implements the transactional outbox pattern for FastAPI applications by generating an `outbox_events` table model, a background ARQ-based dispatcher worker, and an `emit_event()` helper that atomically writes event rows inside the same database transaction as the business write. This eliminates the **dual-write problem**: when an app first `db.commit()`s an order and then publishes `OrderCreated` to Kafka, any crash or network hiccup between those two steps leaves the system permanently inconsistent — downstream consumers never see the event even though the order exists. With an outbox, the publish step is deferred and driven by a poller that reads committed outbox rows, dispatches them, and marks them delivered; if anything fails the row stays unprocessed and a retry happens, so the guarantee is **at-least-once delivery of every successfully committed business write**.

The dispatcher uses PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers can pull from the same outbox table in parallel without stepping on each other, exponential-backoff retries (`1s → 5s → 30s → 5m → 30m`) with a configurable max attempts before dead-lettering, and pluggable sinks so the same outbox can fan out to webhooks (TOOL-015), SSE (TOOL-014), Kafka, or an event bus of your choice. Key design decisions: deduplication IDs on every event so idempotent consumers can drop replays safely, a background pruner that archives delivered events after 7 days to keep the table small (configurable), a dead-letter table for events that exhaust retries so operators can inspect failures without blocking the live pipeline, and `/outbox/metrics` + `/outbox/dlq` admin endpoints for observability. Integrates cleanly with TOOL-005 (audit log) to provide a tamper-evident chain of every external event the system ever emitted.

## 3. Performance SLOs

| Metric | Target | Why |
|--------|--------|-----|
| Tool execution time | < 5s | Must complete during deployment without blocking |
| Files modified | ≤ 6 | Existing models, migrations, and config files |
| Files created | ≥ 9 | Model, migration, worker, helpers, tests |
| `emit_event()` overhead | < 1ms | Single INSERT must not impact request latency |
| Dispatcher poll cycle | < 500ms | For full batch_size=100 with indexes |
| Per-event dispatch latency (p99) | < 200ms | Time from poll to target delivery |
| Migration runtime | 0s | Table creation happens in new migration |
| Memory overhead | < 5MB | Dispatcher worker resident set size |
| Event retention | 7 days | Balances audit needs with storage costs |

---

## 4. Code Examples (Before / After)

### 4.1 Base model: BEFORE
```python
# app/models/base.py
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
```

### 4.2 Base model: AFTER
```python
# app/models/base.py
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """Mixin adding created_at timestamp with timezone."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
```

### 4.3 Outbox model (NEW)
```python
# app/models/outbox.py
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from sqlalchemy import JSON, String, Text, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OutboxEvent(Base, TimestampMixin):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    aggregate_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    aggregate_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)

    __table_args__ = (
        Index(
            "ix_outbox_events_undelivered",
            "created_at",
            postgresql_where=text("dispatched_at IS NULL AND status = 'pending'"),
        ),
        Index("ix_outbox_events_aggregate", "aggregate_type", "aggregate_id"),
    )
```

### 4.4 Outbox service (NEW)
```python
# app/services/outbox.py
import json
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxEvent


class OutboxService:
    """Service for emitting and managing outbox events."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        aggregate_id: Optional[str] = None,
        aggregate_type: Optional[str] = None,
    ) -> UUID:
        """
        Atomically write event to outbox within current transaction.
        Returns the generated event ID.
        """
        if not self.session.in_transaction():
            raise RuntimeError(
                "Outbox.emit() must be called within an active transaction"
            )

        # Validate payload size (64KB limit)
        payload_json = json.dumps(payload)
        if len(payload_json) > 65536:
            raise ValueError("Payload exceeds 64KB limit")

        event = OutboxEvent(
            event_type=event_type,
            payload=payload,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            status="pending",
        )
        self.session.add(event)
        await self.session.flush([event])
        return event.id

    async def mark_dispatched(self, event_id: UUID) -> None:
        """Mark an event as successfully dispatched."""
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(dispatched_at=datetime.utcnow(), status="delivered")
        )
        await self.session.execute(stmt)

    async def mark_failed(self, event_id: UUID, error: str, max_retries: int = 5) -> None:
        """Record a dispatch failure and update status."""
        stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                attempts=OutboxEvent.attempts + 1,
                last_error=error[:512],
                status=(
                    text("'dead'")
                    if OutboxEvent.attempts + 1 >= max_retries
                    else text("'pending'")
                ),
            )
        )
        await self.session.execute(stmt)
```

### 4.5 Dispatcher worker (NEW)
```python
# app/workers/outbox_dispatcher.py
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Literal

import arq
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_maker
from app.models.outbox import OutboxEvent
from app.services.outbox import OutboxService

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    """Worker that polls and dispatches outbox events."""

    def __init__(
        self,
        poll_seconds: float = 1.0,
        batch_size: int = 100,
        max_retries: int = 5,
        targets: List[Literal["webhook", "sse", "kafka"]] = None,
    ):
        self.poll_seconds = poll_seconds
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.targets = targets or ["webhook"]

    async def _dispatch_to_targets(
        self, event: OutboxEvent, targets: List[str]
    ) -> bool:
        """Dispatch event to all configured targets."""
        all_succeeded = True
        
        if "webhook" in targets:
            try:
                await self._send_webhook(event)
            except Exception as e:
                logger.error(f"Webhook dispatch failed for {event.id}: {e}")
                all_succeeded = False
                
        if "sse" in targets:
            try:
                await self._publish_sse(event)
            except Exception as e:
                logger.error(f"SSE dispatch failed for {event.id}: {e}")
                all_succeeded = False
                
        if "kafka" in targets:
            try:
                await self._produce_kafka(event)
            except Exception as e:
                logger.error(f"Kafka dispatch failed for {event.id}: {e}")
                all_succeeded = False
                
        return all_succeeded

    async def _send_webhook(self, event: OutboxEvent) -> None:
        """Send event to configured webhook endpoint."""
        # Implementation depends on existing webhook_sender module
        from app.services.webhook import send_webhook
        await send_webhook(
            event_type=event.event_type,
            payload=event.payload,
            event_id=str(event.id)
        )

    async def poll_and_dispatch(self, ctx: dict) -> None:
        """Main polling loop - runs continuously in ARQ worker."""
        while True:
            try:
                async with async_session_maker() as session:
                    # SKIP LOCKED prevents duplicate processing by multiple workers
                    stmt = (
                        select(OutboxEvent)
                        .where(
                            OutboxEvent.dispatched_at.is_(None),
                            OutboxEvent.status == "pending",
                            OutboxEvent.attempts < self.max_retries,
                        )
                        .order_by(OutboxEvent.created_at)
                        .limit(self.batch_size)
                        .with_for_update(skip_locked=True)
                    )
                    
                    result = await session.execute(stmt)
                    events = result.scalars().all()
                    
                    for event in events:
                        async with session.begin_nested():
                            outbox_service = OutboxService(session)
                            try:
                                success = await self._dispatch_to_targets(event, self.targets)
                                if success:
                                    await outbox_service.mark_dispatched(event.id)
                                else:
                                    await outbox_service.mark_failed(
                                        event.id,
                                        "One or more targets failed",
                                        self.max_retries
                                    )
                            except Exception as e:
                                await outbox_service.mark_failed(
                                    event.id, str(e), self.max_retries
                                )
                                logger.exception(f"Dispatch failed for event {event.id}")
                    
                    await session.commit()
                    
            except Exception as e:
                logger.exception("Error in outbox dispatcher loop")
                
            await asyncio.sleep(self.poll_seconds)
```

### 4.6 CRUD integration: BEFORE
```python
# app/crud/items.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.schemas.item import ItemCreate


async def create_item(
    session: AsyncSession,
    *,
    item_in: ItemCreate,
    owner_id: UUID
) -> Item:
    """Create item without outbox event."""
    item = Item(**item_in.model_dump(), owner_id=owner_id)
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_item(
    session: AsyncSession,
    *,
    item_id: UUID,
    item_in: ItemUpdate
) -> Item:
    """Update item without outbox event."""
    stmt = select(Item).where(Item.id == item_id)
    result = await session.execute(stmt)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    for field, value in item_in.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
        
    await session.commit()
    await session.refresh(item)
    return item
```

### 4.7 CRUD integration: AFTER
```python
# app/crud/items.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.item import Item
from app.schemas.item import ItemCreate, ItemUpdate
from app.services.outbox import OutboxService


async def create_item(
    session: AsyncSession,
    *,
    item_in: ItemCreate,
    owner_id: UUID
) -> Item:
    """Create item with outbox event emitted atomically."""
    async with session.begin():
        item = Item(**item_in.model_dump(), owner_id=owner_id)
        session.add(item)
        await session.flush()
        
        # Emit event in same transaction
        outbox = OutboxService(session)
        await outbox.emit(
            event_type="item.created",
            payload={
                "item_id": str(item.id),
                "title": item.title,
                "owner_id": str(owner_id),
                "created_at": item.created_at.isoformat()
            },
            aggregate_id=str(item.id),
            aggregate_type="item"
        )
    
    await session.refresh(item)
    return item


async def update_item(
    session: AsyncSession,
    *,
    item_id: UUID,
    item_in: ItemUpdate
) -> Item:
    """Update item with outbox event emitted atomically."""
    async with session.begin():
        stmt = select(Item).where(Item.id == item_id)
        result = await session.execute(stmt)
        item = result.scalar_one_or_none()
        
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
            
        changes = {}
        for field, value in item_in.model_dump(exclude_unset=True).items():
            old_value = getattr(item, field)
            setattr(item, field, value)
            changes[field] = {"old": old_value, "new": value}
        
        await session.flush()
        
        if changes:
            outbox = OutboxService(session)
            await outbox.emit(
                event_type="item.updated",
                payload={
                    "item_id": str(item.id),
                    "changes": changes,
                    "updated_at": datetime.utcnow().isoformat()
                },
                aggregate_id=str(item.id),
                aggregate_type="item"
            )
    
    await session.refresh(item)
    return item
```

### 4.8 Outbox admin routes (NEW)
```python
# app/api/endpoints/outbox.py
from datetime import datetime, timedelta
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.outbox import OutboxEvent
from app.schemas.outbox import OutboxStats, OutboxEventResponse

router = APIRouter(prefix="/outbox", tags=["outbox"])


@router.get("/stats", response_model=OutboxStats)
async def get_outbox_stats(
    db: AsyncSession = Depends(get_db),
) -> OutboxStats:
    """Get statistics about outbox events."""
    # Count by status
    stmt = select(
        OutboxEvent.status,
        func.count(OutboxEvent.id).label("count")
    ).group_by(OutboxEvent.status)
    
    result = await db.execute(stmt)
    status_counts = {row.status: row.count for row in result.all()}
    
    # Count undelivered
    undelivered_stmt = select(func.count(OutboxEvent.id)).where(
        OutboxEvent.dispatched_at.is_(None),
        OutboxEvent.status == "pending"
    )
    undelivered = (await db.execute(undelivered_stmt)).scalar() or 0
    
    # Oldest pending
    oldest_stmt = select(func.min(OutboxEvent.created_at)).where(
        OutboxEvent.dispatched_at.is_(None),
        OutboxEvent.status == "pending"
    )
    oldest_pending = (await db.execute(oldest_stmt)).scalar()
    
    return OutboxStats(
        total=sum(status_counts.values()),
        pending=status_counts.get("pending", 0),
        delivered=status_counts.get("delivered", 0),
        dead=status_counts.get("dead", 0),
        undelivered=undelivered,
        oldest_pending=oldest_pending,
        updated_at=datetime.utcnow()
    )


@router.post("/{event_id}/retry", status_code=202)
async def retry_event(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Force retry of a failed or dead event."""
    async with db.begin():
        stmt = select(OutboxEvent).where(OutboxEvent.id == event_id)
        result = await db.execute(stmt)
        event = result.scalar_one_or_none()
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
            
        # Reset for retry
        event.dispatched_at = None
        event.status = "pending"
        event.last_error = None
        
    return {"message": f"Event {event_id} queued for retry"}


@router.post("/cleanup", status_code=202)
async def cleanup_old_events(
    db: AsyncSession = Depends(get_db),
    days: int = Query(7, ge=1, le=90, description="Delete events older than N days")
) -> dict:
    """Clean up delivered events older than specified days."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    stmt = select(func.count(OutboxEvent.id)).where(
        OutboxEvent.dispatched_at.is_not(None),
        OutboxEvent.dispatched_at < cutoff
    )
    count = (await db.execute(stmt)).scalar() or 0
    
    if count > 0:
        delete_stmt = OutboxEvent.__table__.delete().where(
            OutboxEvent.dispatched_at.is_not(None),
            OutboxEvent.dispatched_at < cutoff
        )
        await db.execute(delete_stmt)
        await db.commit()
    
    return {"message": f"Cleaned up {count} events older than {days} days"}
```

### 4.9 Outbox schemas (NEW)
```python
# app/schemas/outbox.py
from datetime import datetime
from typing import Dict, Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class OutboxEventBase(BaseModel):
    event_type: str = Field(..., max_length=128)
    payload: Dict[str, Any]
    aggregate_id: Optional[str] = Field(None, max_length=128)
    aggregate_type: Optional[str] = Field(None, max_length=64)


class OutboxEventCreate(OutboxEventBase):
    """Schema for creating outbox events."""
    pass


class OutboxEventResponse(OutboxEventBase):
    """Schema for outbox event responses."""
    id: UUID
    attempts: int
    status: str
    last_error: Optional[str]
    created_at: datetime
    dispatched_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class OutboxStats(BaseModel):
    """Schema for outbox statistics."""
    total: int
    pending: int
    delivered: int
    dead: int
    undelivered: int
    oldest_pending: Optional[datetime]
    updated_at: datetime
```

### 4.10 Migration file (NEW)
```python
# alembic/versions/0010_create_outbox_events_table.py
"""create outbox_events table

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create outbox_events table
    op.create_table('outbox_events',
        sa.Column('id', UUID(), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('event_type', sa.String(128), nullable=False),
        sa.Column('payload', JSONB(), nullable=False),
        sa.Column('aggregate_id', sa.String(128), nullable=True),
        sa.Column('aggregate_type', sa.String(64), nullable=True),
        sa.Column('dispatched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('status', sa.String(16), server_default='pending', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    
    # Create indexes
    op.create_index('ix_outbox_events_event_type', 'outbox_events', ['event_type'])
    op.create_index('ix_outbox_events_aggregate', 'outbox_events', ['aggregate_type', 'aggregate_id'])
    op.create_index('ix_outbox_events_created_at', 'outbox_events', ['created_at'])
    
    # Partial index for undelivered events (optimizes dispatcher polling)
    op.create_index(
        'ix_outbox_events_undelivered',
        'outbox_events',
        ['created_at'],
        postgresql_where=sa.text("dispatched_at IS NULL AND status = 'pending'")
    )
    
    # Add check constraint for status values
    op.create_check_constraint(
        'ck_outbox_events_status',
        'outbox_events',
        "status IN ('pending', 'delivered', 'dead')"
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_outbox_events_undelivered', table_name='outbox_events')
    op.drop_index('ix_outbox_events_created_at', table_name='outbox_events')
    op.drop_index('ix_outbox_events_aggregate', table_name='outbox_events')
    op.drop_index('ix_outbox_events_event_type', table_name='outbox_events')
    
    # Drop check constraint
    op.drop_constraint('ck_outbox_events_status', 'outbox_events', type_='check')
    
    # Drop table
    op.drop_table('outbox_events')
```

### 4.11 Outbox configuration (NEW)
```python
# app/core/outbox_config.py
from typing import List, Literal
from pydantic import BaseModel, Field


class OutboxConfig(BaseModel):
    """Configuration for outbox pattern."""
    
    # Dispatcher settings
    dispatcher_poll_seconds: float = Field(
        1.0,
        ge=0.1,
        le=60.0,
        description="How often dispatcher polls for new events"
    )
    batch_size: int = Field(
        100,
        ge=1,
        le=1000,
        description="Maximum events to process per poll cycle"
    )
    max_retries: int = Field(
        5,
        ge=0,
        le=20,
        description="Maximum dispatch attempts per event"
    )
    dispatch_targets: List[Literal["webhook", "sse", "kafka"]] = Field(
        ["webhook"],
        description="Enabled delivery targets"
    )
    
    # Retention settings
    retention_days: int = Field(
        7,
        ge=1,
        le=365,
        description="Days to keep delivered events before cleanup"
    )
    
    # Performance settings
    max_payload_size: int = Field(
        65536,
        description="Maximum payload size in bytes (64KB)"
    )
    
    # Worker settings
    worker_concurrency: int = Field(
        1,
        ge=1,
        le=10,
        description="Number of concurrent dispatcher workers"
    )
    
    @property
    def backoff_schedule(self) -> List[int]:
        """Exponential backoff schedule in seconds."""
        return [1, 5, 30, 300, 1800]  # 1s, 5s, 30s, 5m, 30m
    
    def get_backoff_delay(self, attempt: int) -> int:
        """Get backoff delay for given attempt number."""
        if attempt <= 0:
            return 0
        if attempt > len(self.backoff_schedule):
            return self.backoff_schedule[-1]
        return self.backoff_schedule[attempt - 1]


# Default configuration instance
default_config = OutboxConfig()

---

## 5. Quality Standards

| # | Standard | Enforcement |
|---|----------|-------------|
| QS-1 | **Event emission is atomic with business transaction** | `EventEmitter.emit()` raises `RuntimeError` if called outside transaction via `session.in_transaction()` check in `app/core/events.py` |
| QS-2 | **Dispatched events are never reprocessed** | `dispatched_at` column is set via atomic UPDATE in `dispatch_event()` after all targets succeed in `app/workers/dispatcher.py` |
| QS-3 | **Failed events retry with exponential backoff** | `attempts` counter increments and `last_error` updates in `dispatch_event()` with delays 1s→5s→30s→5m→30m |
| QS-4 | **Duplicate dispatch is impossible under concurrency** | `SELECT ... FOR UPDATE SKIP LOCKED` in `poll_outbox()` ensures only one worker processes each batch |
| QS-5 | **Event payloads are bounded and serializable** | `emit_event()` validates payload size <64KB and JSON serializable via `json.dumps()` pre-insert |
| QS-6 | **Dispatcher never blocks API requests** | ARQ worker runs in separate process with dedicated Redis connection pool initialized in `app/core/startup.py` |
| QS-7 | **Dead events require manual intervention** | `max_retries` check in `dispatch_event()` prevents auto-retry after threshold, requiring admin `/retry` endpoint |
| QS-8 | **Outbox table has optimal indexes for polling** | Migration creates `ix_outbox_events_undelivered` on `(dispatched_at, created_at)` with partial index condition |
| QS-9 | **Event retention is strictly enforced** | Scheduled cleanup job deletes rows where `dispatched_at < now() - interval '7 days'` via `DELETE` with time filter |
| QS-10 | **All dispatch targets implement idempotency** | Webhook/SSE/Kafka targets include `event_id` UUID in payload for consumer deduplication |
| QS-11 | **Dispatcher failures are observable** | `last_error` column captures exception details and `attempts` counts retries in `OutboxEvent` model |
| QS-12 | **Tool execution is idempotent** | Migration checks `op.table_exists("outbox_events")` before creation and skips if already present |

## 6. Completeness Criteria

| ID | Criterion | Verification |
|----|-----------|--------------|
| CC-01 | `OutboxEvent` model exists at `app/models/outbox.py` | File exists, contains all declared columns |
| CC-02 | Migration creates `outbox_events` table with correct schema | Inspect `alembic/versions/0009_add_outbox_events.py` upgrade() |
| CC-03 | Migration creates partial index `ix_outbox_events_undelivered` | grep `op.create_index` with `postgresql_where` |
| CC-04 | `EventEmitter` class exists in `app/core/events.py` | File exists, contains `emit()` method with transaction check |
| CC-05 | `event_emitter` context manager binds to session | grep `@contextmanager` in `app/core/events.py` |
| CC-06 | Dispatcher worker implements `poll_outbox()` | File `app/workers/dispatcher.py` exists with SKIP LOCKED query |
| CC-07 | Dispatcher implements exponential backoff | `dispatch_event()` increments attempts and delays based on formula |
| CC-08 | ARQ worker pool initialized at startup | `start_dispatcher()` registered in `app/core/startup.py` |
| CC-09 | Webhook dispatch target implemented | `_dispatch_webhook()` exists with retry logic |
| CC-10 | SSE dispatch target implemented | `_dispatch_sse()` exists with channel publishing |
| CC-11 | Kafka dispatch target implemented | `_dispatch_kafka()` exists with topic selection |
| CC-12 | CRUD operations use `event_emitter` | grep `async with event_emitter` in modified CRUD files |
| CC-13 | Admin endpoint `GET /outbox/stats` exists | Route registered in `app/api/outbox.py` |
| CC-14 | Admin endpoint `POST /outbox/{id}/retry` exists | Route forces `dispatched_at=NULL` and resets attempts |
| CC-15 | Admin endpoint `POST /outbox/{id}/dead` exists | Route sets `dispatched_at=now()` without dispatch |
| CC-16 | Payload size validation (<64KB) | `emit_event()` raises `ValueError` on oversize payload |
| CC-17 | JSON serialization validation | `emit_event()` raises `TypeError` on non-serializable payload |
| CC-18 | Dispatcher settings configurable | `DispatcherSettings` class in `app/workers/dispatcher.py` |
| CC-19 | Dispatcher uses separate DB session | `async_session_maker` in `poll_outbox()` differs from API pool |
| CC-20 | Event retention configurable | `settings.OUTBOX_RETENTION_DAYS` defaults to 7 |
| CC-21 | Test file `tests/test_outbox.py` exists | File contains 30 tests matching test plan |
| CC-22 | Existing tests pass after modification | pytest runs with 0 failures |
| CC-23 | Tool execution time <5s | Time measurement during integration |
| CC-24 | `emit_event()` overhead <1ms | Benchmark T-29 |
| CC-25 | Dispatcher poll cycle <500ms | Benchmark with batch_size=100 |
| CC-26 | Per-event dispatch latency p99 <200ms | Benchmark target delivery |
| CC-27 | Idempotent tool re-run | T-26 verifies no duplicate migrations |
| CC-28 | SKIP LOCKED prevents duplicates | T-07 with concurrent workers |
| CC-29 | Atomic rollback verified | T-01 verifies event not written on failure |
| CC-30 | Backoff schedule correct | T-13 verifies delays 1s→5s→30s→5m→30m |

## 7. Definition of Done

- [ ] All 30 Completeness Criteria verified
- [ ] `OutboxEvent` model passes `ast.parse` validation
- [ ] Migration applies cleanly and rolls back
- [ ] Dispatcher worker starts with ARQ pool
- [ ] `emit_event()` integrates with existing CRUD
- [ ] Admin endpoints return correct HTTP statuses
- [ ] Payload validation rejects invalid inputs
- [ ] Exponential backoff matches documented schedule
- [ ] SKIP LOCKED prevents duplicate dispatch
- [ ] Retention job deletes old events
- [ ] All 30 tests pass in `test_outbox.py`
- [ ] Performance benchmarks meet SLOs
- [ ] Documentation updated with usage examples

## 8. Invariants

| ID | Invariant | Enforcement | Test |
|----|-----------|-------------|------|
| INV-OB-01 | An event is **never** emitted outside a transaction | `EventEmitter.emit()` checks `session.in_transaction()` and raises `RuntimeError` | T-01 |
| INV-OB-02 | A dispatched event is **never** reprocessed automatically | Atomic UPDATE sets `dispatched_at` before commit in `dispatch_event()` | T-07 |
| INV-OB-03 | Failed events **always** retry with exponential backoff | `attempts` counter increments and delay increases in `dispatch_event()` | T-13 |
| INV-OB-04 | Duplicate dispatch is **impossible** under concurrency | `SELECT ... FOR UPDATE SKIP LOCKED` in `poll_outbox()` | T-07 |
| INV-OB-05 | Event payloads are **always** JSON-serializable | `emit_event()` calls `json.dumps()` pre-insert with `TypeError` handler | T-03 |
| INV-OB-06 | Dead events **never** auto-retry | `max_retries` check in `dispatch_event()` prevents further attempts | T-15 |
| INV-OB-07 | The dispatcher **never** blocks API requests | ARQ worker runs in separate process with Redis queue | T-25 |
| INV-OB-08 | Outbox table **never** grows unbounded | Scheduled job deletes rows older than retention period | T-20 |

---

## 9. User Stories

### 9.1 Core functionality (US-01 .. US-05)

**US-01: Emit an event with business transaction**
- **As a** developer integrating the outbox pattern
- **I want** to emit an event atomically with my business logic
- **So that** I avoid the dual-write problem
- **Given:** `create_item()` CRUD operation
- **When:** I call `emit_event(event_type="item.created", payload={"id": 123})` within the same transaction
- **Then:**
  - Event row inserted into `outbox_events` (INV-OB-01)
  - Business data and event committed together (CC-04)
  - Verified by T-01

**US-02: Dispatcher picks up undelivered events**
- **As a** backend engineer
- **I want** the dispatcher to process pending events
- **So that** events reach their targets reliably
- **Given:** 5 events in `outbox_events` with `dispatched_at=NULL`
- **When:** Dispatcher runs `poll_outbox()`
- **Then:**
  - Events dispatched to configured targets (CC-06)
  - `dispatched_at` set after success (INV-OB-02)
  - Verified by T-07

**US-03: Webhook target receives event**
- **As a** developer integrating webhooks
- **I want** events to be delivered to my webhook endpoint
- **So that** external systems stay in sync
- **Given:** Webhook target configured at `https://example.com/webhook`
- **When:** Dispatcher processes an event
- **Then:**
  - HTTP POST sent with event payload (CC-09)
  - Response 200 OK marks event as delivered
  - Verified by T-25

**US-04: SSE target publishes event**
- **As a** developer using server-sent events
- **I want** events to be published to SSE channels
- **So that** clients receive real-time updates
- **Given:** SSE target configured for channel `updates`
- **When:** Dispatcher processes an event
- **Then:**
  - Event published to `updates` channel (CC-10)
  - Clients receive `event: item.created` message
  - Verified by T-26

**US-05: Kafka target produces event**
- **As a** developer using Kafka
- **I want** events to be produced to Kafka topics
- **So that** downstream consumers process them
- **Given:** Kafka target configured for topic `events`
- **When:** Dispatcher processes an event
- **Then:**
  - Event produced to `events` topic (CC-11)
  - Consumer receives message with `event_id`
  - Verified by T-27

### 9.2 Atomicity & transactions (US-06 .. US-10)

**US-06: Rollback excludes event**
- **As a** developer handling failures
- **I want** events to roll back with the transaction
- **So that** I never emit events for failed operations
- **Given:** `create_item()` fails validation
- **When:** Transaction rolls back
- **Then:**
  - No event written to `outbox_events` (INV-OB-01)
  - Verified by T-01

**US-07: SKIP LOCKED prevents duplicates**
- **As a** developer running multiple dispatchers
- **I want** concurrent workers to process distinct events
- **So that** no event is dispatched twice
- **Given:** 2 dispatcher instances polling `outbox_events`
- **When:** Both run `poll_outbox()` simultaneously
- **Then:**
  - Each processes a distinct batch (INV-OB-04)
  - Verified by T-07

**US-08: emit_event() requires transaction**
- **As a** developer integrating the outbox
- **I want** `emit_event()` to enforce transaction context
- **So that** I never accidentally emit outside a transaction
- **Given:** Session not in transaction
- **When:** I call `emit_event()`
- **Then:**
  - `RuntimeError` raised (INV-OB-01)
  - Verified by T-02

**US-09: Dispatcher uses separate session**
- **As a** developer optimizing performance
- **I want** the dispatcher to use a dedicated DB session
- **So that** API requests aren't blocked by dispatcher queries
- **Given:** Dispatcher worker running
- **When:** API handles `GET /items/`
- **Then:**
  - Dispatcher queries use separate pool (CC-19)
  - API response time < 100ms
  - Verified by T-25

**US-10: Retention cleanup runs nightly**
- **As a** developer managing storage
- **I want** old events to be pruned automatically
- **So that** the outbox table doesn't grow unbounded
- **Given:** Events older than 7 days
- **When:** Retention job runs
- **Then:**
  - Old events deleted (INV-OB-08)
  - Verified by T-20

### 9.3 Retry & failure handling (US-11 .. US-15)

**US-11: Failed event retries with backoff**
- **As a** developer handling transient failures
- **I want** failed events to retry with increasing delays
- **So that** temporary issues don't cause permanent failures
- **Given:** Webhook target returns 500
- **When:** Dispatcher processes event
- **Then:**
  - Event retries after 1s, 5s, 30s (INV-OB-03)
  - Verified by T-13

**US-12: Event marked dead after max retries**
- **As a** developer handling persistent failures
- **I want** events to stop retrying after max attempts
- **So that** I can investigate and manually retry
- **Given:** Event with `attempts=5`
- **When:** Dispatcher processes event
- **Then:**
  - Event marked `dead` (INV-OB-06)
  - Verified by T-15

**US-13: Admin force-retries dead event**
- **As a** developer debugging failures
- **I want** to manually retry a dead event
- **So that** I can recover from persistent issues
- **Given:** Dead event id=`abc`
- **When:** Admin calls `POST /outbox/abc/retry`
- **Then:**
  - Event retried immediately (CC-14)
  - Verified by T-19

**US-14: Payload size validation**
- **As a** developer emitting events
- **I want** oversized payloads to be rejected
- **So that** I don't overload the outbox table
- **Given:** Payload > 64KB
- **When:** I call `emit_event()`
- **Then:**
  - `ValueError` raised (CC-16)
  - Verified by T-03

**US-15: JSON serialization validation**
- **As a** developer emitting events
- **I want** non-serializable payloads to be rejected
- **So that** I don't break the dispatcher
- **Given:** Payload contains a `datetime` object
- **When:** I call `emit_event()`
- **Then:**
  - `TypeError` raised (CC-17)
  - Verified by T-04

### 9.4 Integration & observability (US-16 .. US-20)

**US-16: Admin views outbox stats**
- **As a** developer monitoring the system
- **I want** to see counts of pending, delivered, and dead events
- **So that** I can assess system health
- **Given:** Outbox with 10 pending, 5 delivered, 2 dead events
- **When:** Admin calls `GET /outbox/stats`
- **Then:**
  - Response shows counts by status (CC-13)
  - Verified by T-19

**US-17: Tool idempotent on re-run**
- **As a** developer running the tool
- **I want** the tool to skip existing artifacts
- **So that** I can safely re-run it
- **Given:** Outbox pattern already enabled
- **When:** I run `add_outbox_pattern()`
- **Then:**
  - No duplicate migrations created (CC-27)
  - Verified by T-26

**US-18: Migration applies cleanly**
- **As a** developer deploying changes
- **I want** the outbox migration to apply without errors
- **So that** I can enable the pattern safely
- **Given:** Existing database schema
- **When:** `alembic upgrade head` runs
- **Then:**
  - `outbox_events` table created (CC-02)
  - Verified by T-27

**US-19: Migration rolls back cleanly**
- **As a** developer rolling back changes
- **I want** the outbox migration to roll back without errors
- **So that** I can revert safely
- **Given:** Migration applied
- **When:** `alembic downgrade -1` runs
- **Then:**
  - `outbox_events` table dropped (CC-02)
  - Verified by T-28

**US-20: Dispatcher logs retry attempts**
- **As a** developer debugging failures
- **I want** retry attempts to be logged
- **So that** I can diagnose issues
- **Given:** Event fails dispatch
- **When:** Dispatcher retries
- **Then:**
  - `attempts` incremented in `outbox_events` (CC-07)
  - Verified by T-13

### 9.5 Performance & scalability (US-21 .. US-25)

**US-21: emit_event() overhead <1ms**
- **As a** developer optimizing performance
- **I want** `emit_event()` to add minimal overhead
- **So that** API response times stay fast
- **Given:** `create_item()` operation
- **When:** I call `emit_event()`
- **Then:**
  - Overhead <1ms (CC-24)
  - Verified by T-29

**US-22: Dispatcher poll cycle <500ms**
- **As a** developer optimizing dispatcher performance
- **I want** poll cycles to complete quickly
- **So that** events are dispatched promptly
- **Given:** `batch_size=100`
- **When:** Dispatcher runs `poll_outbox()`
- **Then:**
  - Cycle completes <500ms (CC-25)
  - Verified by T-25

**US-23: Per-event dispatch latency p99 <200ms**
- **As a** developer optimizing event delivery
- **I want** events to reach targets quickly
- **So that** downstream systems stay in sync
- **Given:** Webhook target configured
- **When:** Dispatcher processes event
- **Then:**
  - p99 latency <200ms (CC-26)
  - Verified by T-25

**US-24: Outbox table indexes optimize polling**
- **As a** developer optimizing queries
- **I want** the outbox table to have optimal indexes
- **So that** dispatcher queries are fast
- **Given:** `outbox_events` table
- **When:** Dispatcher runs `poll_outbox()`
- **Then:**
  - Query uses `ix_outbox_events_undelivered` (CC-03)
  - Verified by T-07

**US-25: Tool execution time <5s**
- **As a** developer running the tool
- **I want** the tool to complete quickly
- **So that** deployment isn't delayed
- **Given:** Project with 10 models
- **When:** I run `add_outbox_pattern()`
- **Then:**
  - Execution time <5s (CC-23)
  - Verified by T-26

---

## 10. Test Plan

### 10.1 Atomic emission tests

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-01 | Event rolls back with transaction | Session with uncommitted item create | Call `emit_event()` then rollback | No row in `outbox_events` (INV-OB-01) |
| T-02 | emit_event() requires transaction | Session without transaction | Call `emit_event(event_type="test")` | Raises RuntimeError (INV-OB-01) |
| T-03 | Payload size validation | 65KB JSON payload | Call `emit_event()` | Raises ValueError (INV-OB-05) |
| T-04 | JSON serialization validation | Payload with datetime object | Call `emit_event()` | Raises TypeError (INV-OB-05) |
| T-05 | Event committed with transaction | Valid item creation | Call `emit_event()` and commit | Row exists in `outbox_events` |
| T-06 | Closed session rejection | Closed SQLAlchemy session | Call `emit_event()` | Raises InvalidRequestError |

### 10.2 Dispatcher functionality

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-07 | SKIP LOCKED prevents duplicates | 2 dispatcher instances | Simultaneous `poll_outbox()` | Each gets distinct batch (INV-OB-04) |
| T-08 | Single event dispatch | 1 undelivered event | Run `poll_outbox()` | Event marked dispatched (INV-OB-02) |
| T-09 | Batch dispatch limit | 150 undelivered events | Run with `batch_size=100` | Exactly 100 processed |
| T-10 | Ordering guarantee | 3 events with timestamps | Run `poll_outbox()` | Processed in created_at order |
| T-11 | Dispatcher isolation | API request in progress | Run `poll_outbox()` | API response unaffected (INV-OB-07) |
| T-12 | Empty poll cycle | 0 undelivered events | Run `poll_outbox()` | No errors, sleeps poll_seconds |

### 10.3 Retry & failure handling

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-13 | Exponential backoff | Webhook returning 500 | Process event 5 times | Delays: 1s→5s→30s→5m→30m (INV-OB-03) |
| T-14 | Partial target failure | Webhook OK, Kafka down | Dispatch event | Webhook succeeds, Kafka retries |
| T-15 | Max retries enforcement | Event with attempts=5 | Process event | Marked dead, no retry (INV-OB-06) |
| T-16 | Error persistence | Failing webhook | Process event | last_error contains exception |
| T-17 | Attempts increment | First failure | Process event | attempts=1 |
| T-18 | Crash recovery | Dispatcher crash mid-dispatch | Restart worker | Event reprocessed |

### 10.4 Target integration

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-19 | Webhook delivery | Configured endpoint | Process event | HTTP POST with payload |
| T-20 | SSE channel publish | SSE target enabled | Process event | Message on correct channel |
| T-21 | Kafka message produce | Kafka topic configured | Process event | Message on events topic |
| T-22 | Target timeout handling | 10s webhook timeout | Process event | Fails after 10s, retries |
| T-23 | Idempotency keys | All targets | Inspect payloads | Contains event_id UUID |
| T-24 | Mixed target config | Webhook+SSE enabled | Process event | Both targets called |

### 10.5 Admin & maintenance

| # | Test | Setup | Action | Expected |
|---|------|-------|--------|----------|
| T-25 | Stats endpoint | 5 pending, 3 delivered | GET /outbox/stats | Correct counts returned |
| T-26 | Force retry | Dead event | POST /outbox/{id}/retry | attempts=0, reprocessed |
| T-27 | Mark dead | Failed event | POST /outbox/{id}/dead | dispatched_at set |
| T-28 | Retention cleanup | 8-day-old event | Run cleanup job | Event deleted (INV-OB-08) |
| T-29 | emit_event() overhead | Benchmark | 1000 emits | <1ms p99 latency |
| T-30 | Tool idempotency | Existing outbox | Re-run tool | No duplicate migrations |

---

## 11. Interaction Matrix

| Other tool | Order matters? | Interaction | Notes |
|------------|----------------|-------------|-------|
| add_soft_delete | No | ✅ Compatible | Outbox events are independent of soft delete status |
| add_cursor_pagination | No | ✅ Compatible | Pagination applies to admin endpoints, not dispatcher |
| add_search | No | ✅ Compatible | Search indexes don't interact with outbox table |
| add_audit_log | Yes | ⚠️ Caveat | Install audit log AFTER outbox to avoid event recursion |
| add_data_export | No | ✅ Compatible | Export jobs don't interact with outbox events |
| add_bulk_operations | No | ✅ Compatible | Bulk ops emit individual events per record |
| add_multi_tenancy | Yes | ⚠️ Caveat | Install multi-tenancy FIRST so outbox inherits tenant_id |
| add_feature_flags | No | ✅ Compatible | Feature flags don't affect outbox pattern |
| add_api_key_auth | No | ✅ Compatible | Auth is orthogonal to event dispatch |
| add_oauth2_provider | No | ✅ Compatible | OAuth2 tokens don't interact with outbox |
| add_rbac | No | ✅ Compatible | RBAC applies to admin endpoints, not dispatcher |
| add_mfa | No | ✅ Compatible | MFA doesn't affect event emission |
| add_cache_layer | No | ✅ Compatible | Cache is bypassed for outbox dispatcher |
| add_outbox_pattern | N/A | N/A | Self-interaction |
| add_sse | Yes | ⚠️ Caveat | Install SSE FIRST to integrate with dispatcher |

**Conflicts:** None identified.

## 12. Rollback Procedure

### Code rollback (before deploy)
```bash
git checkout -- app/models/base.py
git checkout -- app/core/events.py
git checkout -- app/workers/dispatcher.py
git checkout -- app/crud/items.py
git checkout -- app/core/startup.py
rm -rf app/models/outbox.py
rm -rf alembic/versions/0009_add_outbox_events.py
rm -rf tests/test_outbox.py
```

### Database rollback (after deploy)
```bash
alembic downgrade -1
```
Drops the `outbox_events` table and `ix_outbox_events_undelivered` index.

### Data preservation rollback
**N/A** — no business data is created or migrated by this tool. Nothing to archive.

### Failure mode: tool partially modified files
```bash
git status
git checkout -- app/models/base.py
git checkout -- app/core/events.py
git checkout -- app/workers/dispatcher.py
git checkout -- app/crud/items.py
git checkout -- app/core/startup.py
rm -rf app/models/outbox.py
rm -rf alembic/versions/0009_add_outbox_events.py
rm -rf tests/test_outbox.py
```

### Emergency: Dispatcher worker stuck processing events
1. Stop the ARQ worker process
2. Run `UPDATE outbox_events SET dispatched_at = NULL WHERE dispatched_at IS NOT NULL`
3. Restart the worker

## 13. Edge Cases

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| EC-1 | emit_event() called outside transaction | Tool errors with message: "emit() must be called within a transaction" |
| EC-2 | Payload larger than 64 KB | Tool errors with message: "Payload exceeds maximum size of 64 KB" |
| EC-3 | Payload contains non-JSON-serializable object | Tool errors with message: "Payload must be JSON-serializable" |
| EC-4 | Dispatcher worker process crashes mid-dispatch | Event remains in processing state; next poll picks it up |
| EC-5 | All configured targets fail for an event | Event retries with exponential backoff until max_retries |
| EC-6 | One target succeeds, another fails | Event retried; successful target called again with same event_id |
| EC-7 | Multiple dispatcher instances running | SKIP LOCKED ensures each instance processes distinct events |
| EC-8 | Outbox table grows beyond 1M rows | Query uses ix_outbox_events_undelivered index for fast polling |
| EC-9 | Retention cleanup runs while dispatcher working | Cleanup uses separate WHERE clause; no conflict with dispatcher |
| EC-10 | emit_event() called with closed session | Tool errors with message: "Cannot emit event: session is closed" |
| EC-11 | Event ordering matters but parallelism breaks order | Dispatcher uses ORDER BY created_at but parallel dispatch may reorder |
| EC-12 | Target timeout exceeds poll interval | Event remains in dispatching state; reprocessed after heartbeat expires |
| EC-13 | Network partition between API and DB during emit | Transaction rolls back; event not written to outbox |
| EC-14 | Tool re-run on already-configured project | Idempotent: skips existing artifacts with warning |
| EC-15 | Dispatcher process crashes mid-dispatch | Event row unchanged; next poll picks it up |

## 14. Acceptance Criteria (Final Sign-off)

✅ All 30 Completeness Criteria verified
✅ OutboxEvent model passes ast.parse validation
✅ Migration applies cleanly and rolls back
✅ Dispatcher worker starts with ARQ pool
✅ emit_event() integrates with existing CRUD
✅ Admin endpoints return correct HTTP statuses
✅ Payload validation rejects invalid inputs
✅ Exponential backoff matches documented schedule
✅ SKIP LOCKED prevents duplicate dispatch
✅ End-to-end test: Emit event, verify dispatch, check cleanup

## 15. Implementation Checklist (Ultra-granular)

### 15.1 Pre-flight checks
- [ ] Validate project_dir exists
- [ ] Validate app/ subdirectory exists
- [ ] Validate alembic/versions/ exists
- [ ] Validate SQLAlchemy session factory configured
- [ ] Validate ARQ worker pool initialized
- [ ] Check for existing outbox_events table
- [ ] Verify Redis connection available

### 15.2 Settings configuration
- [ ] Add OUTBOX_RETENTION_DAYS to config.py
- [ ] Add OUTBOX_DISPATCH_TARGETS to config.py
- [ ] Add OUTBOX_MAX_PAYLOAD_SIZE to config.py
- [ ] Add OUTBOX_MAX_RETRIES to config.py
- [ ] Add OUTBOX_BATCH_SIZE to config.py
- [ ] Add OUTBOX_POLL_SECONDS to config.py
- [ ] Add OUTBOX_DISPATCH_TIMEOUT to config.py

### 15.3 Model generation
- [ ] Create app/models/outbox.py
- [ ] Define OutboxEvent model
- [ ] Add TimestampMixin inheritance
- [ ] Define ix_outbox_events_undelivered index
- [ ] Add JSONB payload column
- [ ] Add dispatched_at nullable column
- [ ] Add attempts counter column

### 15.4 Helper/core modules
- [ ] Create app/core/events.py
- [ ] Implement EventEmitter class
- [ ] Add emit() method with transaction check
- [ ] Implement event_emitter context manager
- [ ] Add payload size validation
- [ ] Add JSON serialization validation
- [ ] Add aggregate_id/type support

### 15.5 CRUD integration
- [ ] Modify app/crud/items.py
- [ ] Add event_emitter context manager
- [ ] Call emit() within transaction
- [ ] Pass aggregate_id from created entity
- [ ] Verify atomic commit of business data + event
- [ ] Add error handling for emit failures
- [ ] Verify session binding

### 15.6 Migration generation
- [ ] Compute next revision number
- [ ] Generate 0009_add_outbox_events.py
- [ ] Create outbox_events table
- [ ] Add ix_outbox_events_undelivered index
- [ ] Define JSONB payload column
- [ ] Add dispatched_at nullable column
- [ ] Add attempts counter column

### 15.7 Dispatcher worker
- [ ] Create app/workers/dispatcher.py
- [ ] Implement poll_outbox() function
- [ ] Add SKIP LOCKED query
- [ ] Implement dispatch_event() function
- [ ] Add exponential backoff logic
- [ ] Add max_retries enforcement
- [ ] Implement target-specific dispatch functions

### 15.8 Startup hooks
- [ ] Create app/core/startup.py
- [ ] Add start_dispatcher() function
- [ ] Initialize ARQ worker pool
- [ ] Register dispatcher settings
- [ ] Add stop_dispatcher() function
- [ ] Register cleanup job
- [ ] Verify Redis connection pooling

### 15.9 Admin endpoints
- [ ] Create app/api/routes/outbox.py
- [ ] Add GET /outbox/stats endpoint
- [ ] Add POST /outbox/{id}/retry endpoint
- [ ] Add POST /outbox/{id}/dead endpoint
- [ ] Add RBAC protection
- [ ] Add response schemas
- [ ] Add error handling

### 15.10 Test generation
- [ ] Create tests/test_outbox.py
- [ ] Add atomic emission tests
- [ ] Add dispatcher functionality tests
- [ ] Add retry & failure handling tests
- [ ] Add admin endpoint tests
- [ ] Add integration tests
- [ ] Add performance benchmarks
- [ ] Add idempotency tests

### 15.11 Atomicity
- [ ] Use temp-file + rename pattern
- [ ] Track touched files for rollback
- [ ] Verify atomic migration
- [ ] Verify atomic dispatcher operations
- [ ] Verify atomic emit_event()
- [ ] Verify atomic cleanup job
- [ ] Return rollback report on failure

### 15.12 Documentation updates
- [ ] Append outbox pattern section to KNOWLEDGE.md
- [ ] Add tool entry to manifest.yaml
- [ ] Add tool to SKILL.md tools table
- [ ] Update mcp_server.py with new MCP tool decorator
- [ ] Add usage examples
- [ ] Add troubleshooting guide
- [ ] Add performance tuning tips

### 15.13 Verification
- [ ] Run ast.parse on every modified file
- [ ] Run import audit on the project
- [ ] Run pytest tests/ to verify no regressions
- [ ] Run analyzer to verify benchmark unchanged
- [ ] Measure tool execution time
- [ ] Measure emit_event() overhead
- [ ] Measure dispatcher poll cycle time

## 16. Documentation Output

```json
{
  "status": "success",
  "files_created": [
    "app/models/outbox.py",
    "app/core/events.py",
    "app/workers/dispatcher.py",
    "app/core/startup.py",
    "app/api/routes/outbox.py",
    "alembic/versions/0009_add_outbox_events.py",
    "tests/test_outbox.py",
    "docs/outbox_pattern.md"
  ],
  "files_modified": [
    "app/models/base.py",
    "app/crud/items.py",
    "app/core/config.py",
    "app/main.py"
  ],
  "metrics": {
    "execution_time_ms": 4231,
    "files_changed": 12,
    "lines_added": 612,
    "lines_removed": 24,
    "emit_overhead_ms": 0.8,
    "poll_cycle_ms": 423
  },
  "next_steps": [
    "Run: alembic upgrade head",
    "Run: pytest tests/test_outbox.py -v",
    "Test event emission: modify a CRUD operation to emit an event",
    "Verify dispatcher: check Redis for worker activity",
    "Test admin endpoints: GET /outbox/stats"
  ],
  "warnings": [
    "Payloads larger than 64 KB will be rejected",
    "Non-JSON-serializable payloads will be rejected"
  ],
  "notes": [
    "Outbox pattern enabled with default retention of 7 days",
    "Dispatcher worker configured with batch_size=100",
    "Webhook dispatch target enabled by default",
    "Existing tests still pass: 47/47"
  ]
}
