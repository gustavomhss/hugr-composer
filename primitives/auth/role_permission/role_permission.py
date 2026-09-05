"""ORM model for RolePermission."""

from __future__ import annotations
import uuid
from sqlalchemy import Boolean, DateTime, String, Uuid, func, ForeignKey, LargeBinary, Integer, Index, JSON, Text, Enum as SQLEnum, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models.base import Base


class RolePermission(Base):
    """Many-to-many binding between Role and Permission.

    Attributes:
        id: UUID primary key.
        role_id: FK to roles.
        permission_id: FK to permissions.
        role: ORM relationship to Role.
    """
    __tablename__ = 'role_permissions'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('roles.id', ondelete='CASCADE'), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('permissions.id', ondelete='CASCADE'), nullable=False)
    role: Mapped[Role] = relationship(back_populates='permissions')
    __table_args__ = (UniqueConstraint('role_id', 'permission_id', name='uq_role_permissions'),)
