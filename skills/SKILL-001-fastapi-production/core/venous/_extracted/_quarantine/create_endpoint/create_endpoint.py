from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import secrets
import uuid


async def create_endpoint(session: AsyncSession, in_: WebhookCreate, user_id: uuid.UUID) -> WebhookEndpoint:
    """Create a new webhook endpoint.

    Args:
        session: Async database session.
        in_: Creation input schema.
        user_id: UUID of the owning user.

    Returns:
        The persisted ``WebhookEndpoint`` instance.
    """
    ep = WebhookEndpoint(url=str(in_.url), description=in_.description, events=in_.events, secret=secrets.token_hex(32), user_id=user_id)
    session.add(ep)
    await session.flush()
    return ep
