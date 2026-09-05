from __future__ import annotations
"""ORM model for Passkey."""

from sqlalchemy import BigInteger
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class Passkey(Base):
    """Stored WebAuthn credential for a user.

    One user may have multiple passkeys (one per authenticator device).
    The public key is stored as raw bytes (COSE-encoded CBOR).

    Attributes:
        id: Primary key UUID.
        credential_id: WebAuthn credential identifier (base64url bytes).
        public_key: COSE-encoded CBOR public key bytes.
        sign_count: Monotonically increasing counter, cloned-device detection.
        aaguid: Authenticator AAGUID (device model identifier).
        user_id: FK to users.id (CASCADE DELETE).
        created_at: Immutable creation timestamp.
        last_used_at: Updated on every successful authentication.
    """
    __tablename__ = 'passkeys'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    aaguid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint('credential_id', name='uq_passkey_credential_id'),)
