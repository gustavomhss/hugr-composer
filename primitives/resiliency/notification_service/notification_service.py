"""Pure Python primitive: NotificationService."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class NotificationService:
    """Facade for notification lifecycle operations."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with an active async database session."""
        self._session = session

    async def send(self, user_id: uuid.UUID, title: str, body: str, channel: str='in_app') -> None:
        """Create a notification and dispatch it through *channel*.

        Args:
            user_id: Recipient's user UUID.
            title: Short notification title.
            body: Full notification body text.
            channel: Delivery channel — ``"in_app"``, ``"push"``,
                or ``"email"``.  Defaults to ``"in_app"``.
        """
        data = NotificationCreate(user_id=user_id, title=title, body=body, channel=channel)
        notif = await create_notification(self._session, data)
        await dispatch(notif, channel=channel)

    async def list_unread(self, user_id: uuid.UUID, *, limit: int=50, offset: int=0) -> Sequence:
        """Return unread notifications for *user_id*, newest first."""
        return await list_unread(self._session, user_id, limit=limit, offset=offset)

    async def mark_read(self, notification_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        """Mark a single notification read; returns ``True`` if updated."""
        return await mark_read(self._session, notification_id, user_id)

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Bulk-mark all unread notifications read; returns count updated."""
        return await mark_all_read(self._session, user_id)

    async def count_unread(self, user_id: uuid.UUID) -> int:
        """Return the unread notification count for the badge widget."""
        return await count_unread(self._session, user_id)
