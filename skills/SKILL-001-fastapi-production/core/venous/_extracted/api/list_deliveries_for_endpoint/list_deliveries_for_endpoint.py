from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def list_deliveries_for_endpoint(session: AsyncSession, *, endpoint_id: uuid.UUID | str) -> list[WebhookDelivery]:
    """Return all deliveries for an endpoint, newest first.

    Args:
        session: Async database session.
        endpoint_id: UUID of the endpoint.

    Returns:
        List of ``WebhookDelivery`` instances ordered by scheduled_at desc.
    """
    stmt = select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id).order_by(WebhookDelivery.scheduled_at.desc())
    return list((await session.execute(stmt)).scalars().all())
