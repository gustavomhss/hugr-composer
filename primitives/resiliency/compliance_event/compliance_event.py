"""ORM model for ComplianceEvent."""

from __future__ import annotations
from datetime import datetime
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class ComplianceEvent(Base):
    """Append-only audit record for compliance actions.

    Each row captures one compliance-relevant event (PII access, erasure,
    retention purge, encryption rotation, etc.) with enough context for
    SOC2 / GDPR / HIPAA evidence packages.
    """
    __tablename__ = 'compliance_events'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    table_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    def __repr__(self) -> str:
        """Return a concise string representation."""
        return f'<ComplianceEvent id={self.id!r} type={self.event_type!r} at={self.created_at!r}>'
