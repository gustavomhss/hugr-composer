from __future__ import annotations
from datetime import datetime
import uuid


class UserPresence(Base):
    """Tracks the online/offline state of a user.

    Attributes:
        id: UUID primary key.
        user_id: UUID of the user (not FK — presence is ephemeral).
        device_id: Device identifier for multi-device support.
        status: Current status string (``"online"`` or ``"offline"``).
        last_seen: UTC timestamp of the most recent heartbeat.
    """
    __tablename__ = 'user_presence'
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default='default')
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default='offline')
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
