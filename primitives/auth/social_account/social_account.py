"""ORM model for SocialAccount."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class SocialAccount(Base):
    """Linked social provider account for a user.

    One user may have multiple rows (one per provider).  Tokens are
    never persisted; only the provider user ID and email are stored.

    Attributes:
        id: Primary key UUID.
        provider: Provider name (google | github | apple).
        provider_user_id: Stable unique ID issued by the provider.
        provider_email: Email reported by provider at last login.
        user_id: FK to users.id (CASCADE DELETE).
        created_at: Immutable creation timestamp.
        updated_at: Updated on every login.
    """
    __tablename__ = 'social_accounts'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint('provider', 'provider_user_id', name='uq_social_provider_user'), CheckConstraint("provider IN ('google','github','apple')", name='ck_social_provider'))
