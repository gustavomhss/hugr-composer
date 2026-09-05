"""ORM model for OutboxEvent."""

from __future__ import annotations
from typing import Any
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class OutboxEvent(Base):
    """Transactional outbox event row.

    Written atomically inside the same DB transaction as the business write.
    Dispatcher polls for pending rows and delivers them at-least-once.

    Attributes:
        id: UUID primary key.
        event_type: Domain event name (e.g. ``OrderCreated``).
        aggregate_type: Entity type (e.g. ``Order``).
        aggregate_id: Entity identifier for correlation.
        payload: JSON payload (JSONB on PostgreSQL).
        status: ``pending`` → ``delivered`` | ``dead``.
        attempts: Delivery attempt counter.
        last_error: Truncated error string from last failure.
        dispatched_at: Timestamp of successful delivery.
        created_at: Row creation timestamp (server-side).
        idempotency_key: Optional dedup key for downstream consumers.
    """
    __tablename__ = 'outbox_events'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default='pending', nullable=False, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    __table_args__ = (Index('ix_outbox_events_pending', 'created_at', postgresql_where=text("status = 'pending' AND dispatched_at IS NULL")), Index('ix_outbox_events_aggregate', 'aggregate_type', 'aggregate_id'))
