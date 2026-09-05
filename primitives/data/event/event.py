"""ORM model for Event."""

from __future__ import annotations
from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import DateTime, String, Uuid, func, Integer, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Event(Base):
    """Append-only event row in the event store.

    Attributes:
        id: UUID primary key (event_id).
        stream_id: Opaque aggregate/stream identifier.
        event_type: Discriminator string for the event kind.
        data_json: JSON payload for this event instance.
        version: Monotonically increasing sequence number within the stream.
        created_at: UTC timestamp (server default — immutable after insert).
    """
    __tablename__ = 'events'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    stream_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    data_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (Index('ix_events_stream_id_version', 'stream_id', 'version', unique=True),)
