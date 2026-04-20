from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def upsert_duplicate(session: AsyncSession, *, provider: str, provider_event_id: str, event_type: str) -> InboundWebhook:
    """Persist a duplicate event record for audit visibility.

    Args:
        session: Async database session.
        provider: Provider name string.
        provider_event_id: Provider-assigned event id.
        event_type: Provider event type string.

    Returns:
        The persisted duplicate ``InboundWebhook`` row.
    """
    row = InboundWebhook(id=uuid.uuid4(), provider=provider, provider_event_id=f'dup:{provider_event_id}:{uuid.uuid4().hex[:8]}', event_type=event_type, payload={}, raw_headers={}, status='duplicate')
    session.add(row)
    await session.flush()
    return row
