"""ORM model for WebhookDelivery."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class WebhookDelivery(Base):
    """A single webhook delivery attempt record.

    Attributes:
        id: UUID primary key.
        endpoint_id: FK to the parent WebhookEndpoint.
        event_id: Logical event UUID shared across all deliveries of one event.
        event_type: String event type (e.g. ``item.created``).
        payload: JSON event payload.
        status: One of pending / succeeded / failed / dead.
        attempt_number: 1-indexed delivery attempt counter.
        http_status: HTTP response status code, if available.
        response_body: First 4096 chars of the response body.
        error: Error summary string (max 500 chars).
        scheduled_at: When this delivery was created/scheduled.
        delivered_at: UTC timestamp of successful delivery.
    """
    __tablename__ = 'webhook_deliveries'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    endpoint_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('webhook_endpoints.id', ondelete='CASCADE'), nullable=False, index=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(127), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='pending')
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default='0')
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    endpoint: Mapped['WebhookEndpoint'] = relationship(back_populates='deliveries')
    __table_args__ = (CheckConstraint("status IN ('pending','succeeded','failed','dead')", name='ck_webhook_deliveries_status'),)
