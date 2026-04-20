from __future__ import annotations
from datetime import datetime
import uuid


class MFARecoveryCode(Base):
    """Single-use recovery code row (Argon2id hash).

    Attributes:
        id: UUID primary key.
        device_id: FK to mfa_devices (CASCADE delete).
        code_hash: Argon2id hash of the plaintext recovery code.
        used_at: UTC timestamp when the code was consumed, or NULL.
        device: ORM back-reference to MFADevice.
    """
    __tablename__ = 'mfa_recovery_codes'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    device_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey('mfa_devices.id', ondelete='CASCADE'), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device: Mapped[MFADevice] = relationship(back_populates='recovery_codes')
