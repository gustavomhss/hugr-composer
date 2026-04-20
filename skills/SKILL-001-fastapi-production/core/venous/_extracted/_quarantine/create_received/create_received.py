from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


async def create_received(session: AsyncSession, *, provider: str, provider_event_id: str, event_type: str, payload: dict[str, Any], raw_headers: dict[str, str]) -> InboundWebhook:
    """Persist a newly received inbound webhook event.

    Args:
        session: Async database session.
        provider: Provider name string.
        provider_event_id: Provider-assigned event identifier.
        event_type: Provider event type string.
        payload: Parsed event payload.
        raw_headers: Lowercased request headers.

    Returns:
        The persisted ``InboundWebhook`` instance.
    """
    row = InboundWebhook(provider=provider, provider_event_id=provider_event_id, event_type=event_type, payload=payload, raw_headers=raw_headers)
    session.add(row)
    await session.flush()
    return row
