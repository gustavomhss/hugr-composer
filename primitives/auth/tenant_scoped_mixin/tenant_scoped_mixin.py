"""SQLAlchemy mixin: TenantScopedMixin."""

from __future__ import annotations

from sqlalchemy import DateTime, String, Uuid, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, declared_attr

from app.models.base import Base


class TenantScopedMixin:
    """Add tenant_id FK to every business model for hard isolation.

    Inherit *before* Base::

        class Item(TenantScopedMixin, Base): ...

    Attributes:
        tenant_id: Non-nullable FK to tenants.id.  ON DELETE RESTRICT
            ensures a tenant with live rows cannot be deleted.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(Uuid, ForeignKey('tenants.id', ondelete='RESTRICT'), nullable=False, index=True)
