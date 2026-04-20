from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def list_recent(session: AsyncSession, *, provider: str | None=None, limit: int=50) -> list[InboundWebhook]:
    """Return recent inbound webhook records, newest first.

    Args:
        session: Async database session.
        provider: Optional provider filter.
        limit: Maximum records to return (default 50).

    Returns:
        List of ``InboundWebhook`` instances.
    """
    stmt = select(InboundWebhook).order_by(InboundWebhook.received_at.desc()).limit(limit)
    if provider is not None:
        stmt = stmt.where(InboundWebhook.provider == provider)
    return list((await session.execute(stmt)).scalars().all())
