from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_endpoints_for_event(session: AsyncSession, *, event_type: str) -> list[WebhookEndpoint]:
    """Return active endpoints subscribed to *event_type*.

    Filters active endpoints whose ``events`` JSON list contains the
    given *event_type*.  Uses a database-agnostic approach (works with
    both PostgreSQL and SQLite).

    Args:
        session: Async database session.
        event_type: Event type string to match.

    Returns:
        List of matching active ``WebhookEndpoint`` instances.
    """
    stmt = select(WebhookEndpoint).where(WebhookEndpoint.status == 'active')
    rows = list((await session.execute(stmt)).scalars().all())
    return [ep for ep in rows if event_type in (ep.events or [])]
