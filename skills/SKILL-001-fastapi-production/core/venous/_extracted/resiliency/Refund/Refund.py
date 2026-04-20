from __future__ import annotations
from datetime import datetime
import uuid


class Refund(Base):
    """A Stripe refund record.

    Attributes:
        id: Internal UUID primary key.
        payment_id: FK to the associated payment row.
        stripe_refund_id: Stripe Refund object id (unique).
        amount_cents: Refunded amount in the smallest currency unit.
        reason: Stripe-accepted reason string.
        status: Lifecycle status — pending, succeeded, or failed.
        requested_by: FK to the user who triggered the refund (nullable).
        created_at: UTC timestamp when the row was inserted.
    """
    __tablename__ = 'refunds'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('payments.id', ondelete='CASCADE'), nullable=False, index=True)
    stripe_refund_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default='pending')
    requested_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (CheckConstraint("status IN ('pending','succeeded','failed')", name='ck_refunds_status'), Index('ix_refunds_payment_created', 'payment_id', 'created_at'))
