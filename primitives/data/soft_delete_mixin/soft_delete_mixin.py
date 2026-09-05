"""SQLAlchemy mixin: SoftDeleteMixin."""

from __future__ import annotations

from sqlalchemy import DateTime, String, Uuid, func, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, declared_attr

from app.models.base import Base


class SoftDeleteMixin:
    """Mix-in adding is_deleted, deleted_at, and deleted_by columns.

    Inherit *before* Base::

        class Item(SoftDeleteMixin, Base): ...

    Attributes:
        is_deleted: Boolean flag.  DB server_default='false' means
            ALTER TABLE is metadata-only on PG 11+ (no table rewrite).
        deleted_at: UTC timestamp of deletion, nullable.
        deleted_by: FK to users.id, nullable, SET NULL on user delete.
    """

    @declared_attr
    def is_deleted(cls) -> _sd_Mapped[bool]:
        return _sd_mapped_column(_sd_Boolean, default=False, nullable=False, server_default='false')

    @declared_attr
    def deleted_at(cls) -> _sd_Mapped[_sd_datetime | None]:
        return _sd_mapped_column(_sd_DateTime(timezone=True), nullable=True)

    @declared_attr
    def deleted_by(cls) -> _sd_Mapped[_sd_uuid.UUID | None]:
        return _sd_mapped_column(_sd_Uuid, _sd_ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
