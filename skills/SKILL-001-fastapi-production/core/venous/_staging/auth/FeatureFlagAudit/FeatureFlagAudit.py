from __future__ import annotations
from datetime import datetime
import uuid


class FeatureFlagAudit(Base):
    """Immutable audit record for every flag create/update/delete.

    Attributes:
        id: UUID primary key.
        flag_id: FK to the affected FeatureFlag.
        action: One of 'create', 'update', 'delete'.
        before_state: JSON snapshot before the change (None on create).
        after_state: JSON snapshot after the change (None on delete).
        actor_id: UUID of the user who triggered the change.
        created_at: UTC timestamp of the audit event.
    """
    __tablename__ = 'feature_flag_audit'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    flag_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('feature_flags.id', ondelete='CASCADE'), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    flag: Mapped[FeatureFlag] = relationship(back_populates='audit_log')
