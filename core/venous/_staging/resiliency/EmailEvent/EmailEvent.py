from __future__ import annotations
from datetime import datetime
import uuid


class EmailEvent(Base):
    """Audit record for a single email delivery event."""
    __tablename__ = 'email_events'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    message_id: Mapped[str] = mapped_column(String(255), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    recipient_redacted: Mapped[str] = mapped_column(String(128))
    provider: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
