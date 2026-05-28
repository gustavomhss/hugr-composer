from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


class DeliveryTracker:
    """Async helper for recording and querying email delivery events."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an active async database session."""
        self._session = session

    async def track(self, *, message_id: str, event_type: str, recipient: str, provider: str) -> None:
        """Record a delivery event for *message_id*.

        Args:
            message_id: Provider-assigned message identifier.
            event_type: One of sent / delivered / bounced / complained.
            recipient: Full recipient address (redacted before storing).
            provider: Provider name (resend / postmark / sendgrid).
        """
        from app.models.email_event import EmailEvent
        event = EmailEvent(id=uuid.uuid4(), message_id=message_id, event_type=event_type, recipient_redacted=_redact_email(recipient), provider=provider, occurred_at=datetime.now(timezone.utc))
        self._session.add(event)
        await self._session.commit()
        logger.info('email.delivery provider=%s event=%s msg_id=%s', provider, event_type, message_id)

    async def list_events(self, *, limit: int=50, offset: int=0) -> list:
        """Return the most recent email events, newest first.

        Args:
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            List of ``EmailEvent`` ORM instances.
        """
        from app.models.email_event import EmailEvent
        stmt = select(EmailEvent).order_by(EmailEvent.occurred_at.desc()).limit(limit).offset(offset)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
