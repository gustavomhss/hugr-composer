"""ORM model for MfaDevice."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class MFADevice(Base):
    """One TOTP device per user (unique on user_id).

    The TOTP secret is stored encrypted with Fernet (``secret_enc``).
    Enrollment is confirmed when ``confirmed_at`` is set.

    Attributes:
        id: UUID primary key.
        user_id: FK to users (one device per user, CASCADE delete).
        type: Device type — currently only ``'totp'``.
        secret_enc: Fernet-encrypted base32 TOTP secret bytes.
        confirmed_at: UTC timestamp when the user confirmed enrollment, or NULL.
        last_used_at: UTC timestamp of the most recent successful challenge.
        created_at: UTC creation timestamp.
        recovery_codes: Related MFARecoveryCode rows.
    """
    __tablename__ = 'mfa_devices'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, unique=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False, server_default='totp')
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    recovery_codes: Mapped[list['MFARecoveryCode']] = relationship(back_populates='device', cascade='all, delete-orphan')
    __table_args__ = (CheckConstraint("type IN ('totp')", name='ck_mfa_devices_type'),)
