"""ORM model for Permission."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class Permission(Base):
    """A single resource:action permission token (e.g. 'items:write').

    Attributes:
        id: UUID primary key.
        code: Canonical permission code in resource:action format.
        description: Optional human-readable description.
        created_at: UTC creation timestamp.
    """
    __tablename__ = 'permissions'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(127), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("code LIKE '%:%'", name='ck_permissions_code_format'),)
