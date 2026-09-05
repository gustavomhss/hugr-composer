"""ORM model for Notification."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class Notification(Base):
    """Persistent notification record.

    Attributes:
        id: UUID primary key.
        user_id: Owner's user UUID (foreign key).
        title: Short notification title (≤255 chars).
        body: Full notification body text.
        channel: Delivery channel used (``in_app``, ``push``, ``email``).
        read_at: Timestamp when the notification was read; ``None`` if unread.
        created_at: Timestamp of creation (server-side default).
    """
    __tablename__ = 'notifications'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default='')
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default='in_app')
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
