from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import uuid


async def create_delivery(session: AsyncSession, *, endpoint_id: uuid.UUID, event_id: uuid.UUID, event_type: str, payload: dict[str, Any]) -> WebhookDelivery:
    """Create a new delivery row for a webhook endpoint.

    Args:
        session: Async database session.
        endpoint_id: UUID of the target endpoint.
        event_id: Logical event UUID (shared across all deliveries).
        event_type: Event type string.
        payload: JSON payload dict.

    Returns:
        The persisted ``WebhookDelivery`` instance.
    """
    delivery = WebhookDelivery(endpoint_id=endpoint_id, event_id=event_id, event_type=event_type, payload=payload)
    session.add(delivery)
    await session.flush()
    return delivery
