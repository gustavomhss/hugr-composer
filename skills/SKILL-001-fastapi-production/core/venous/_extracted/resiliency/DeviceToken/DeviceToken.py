from __future__ import annotations
from datetime import datetime
import uuid


class DeviceToken(Base):
    """Stores a user's platform-specific push notification token."""
    __tablename__ = 'device_tokens'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
