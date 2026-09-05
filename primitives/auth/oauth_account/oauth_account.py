"""ORM model for OAuthAccount."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OAuthAccount(Base):
    """Linked OAuth provider account for a user.

    One user may have multiple rows (one per provider).  Provider tokens
    are stored encrypted at rest; plaintext never hits the database.

    Attributes:
        id: Primary key UUID.
        provider: Provider name (google | github | facebook | microsoft).
        provider_user_id: Stable unique ID issued by the provider.
        provider_email: Email reported by provider at last login.
        user_id: FK to users.id (CASCADE DELETE).
        access_token_enc: Fernet-encrypted access token bytes.
        refresh_token_enc: Fernet-encrypted refresh token bytes.
        expires_at: Optional provider access token expiry (UTC).
        created_at: Immutable creation timestamp.
        updated_at: Updated on every upsert.
    """
    __tablename__ = 'oauth_accounts'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    access_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    __table_args__ = (UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user'), CheckConstraint("provider IN ('google','github','facebook','microsoft')", name='ck_oauth_provider'))
