"""ORM model for OutboxDlq."""

from __future__ import annotations
from typing import Any
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class OutboxDlq(Base):
    """Dead-letter queue for events that exhausted all retry attempts.

    Attributes:
        id: UUID primary key.
        original_event_id: FK to the original OutboxEvent.id.
        event_type: Copied from original event.
        payload: Copied from original event.
        final_error: Last error that caused DLQ placement.
        created_at: When the event was moved to DLQ.
    """
    __tablename__ = 'outbox_dlq'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_event_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    final_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
