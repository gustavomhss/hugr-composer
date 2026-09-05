"""ORM model for OtpCode."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class OtpCode(Base):
    """SMS one-time password code record.

    One row per OTP send attempt.  Rows are never deleted; verified
    and expired codes are kept for audit purposes.

    Attributes:
        id: Primary key UUID.
        phone: Phone number in E.164 format.
        code: Plain-text OTP digits (short-lived, not a secret at rest).
        expires_at: UTC timestamp when this code expires.
        verified: True once the user has successfully verified this code.
        created_at: Creation timestamp.
    """
    __tablename__ = 'otp_codes'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
