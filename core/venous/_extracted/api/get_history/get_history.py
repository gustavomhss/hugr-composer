from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def get_history(session: AsyncSession, *, room_id: uuid.UUID, limit: int=50, before_id: uuid.UUID | None=None) -> list[ChatMessage]:
    """Return the most recent messages in *room_id*, newest last.

    Args:
        session: Async database session.
        room_id: UUID of the room.
        limit: Maximum number of messages to return (default 50).
        before_id: Optional pagination cursor — return messages strictly
            older than this message id.

    Returns:
        List of ``ChatMessage`` instances, oldest first (UI friendly).
    """
    stmt = select(ChatMessage).where(ChatMessage.room_id == room_id).order_by(ChatMessage.created_at.desc()).limit(limit)
    if before_id is not None:
        anchor_stmt = select(ChatMessage.created_at).where(ChatMessage.id == before_id)
        anchor = (await session.execute(anchor_stmt)).scalar_one_or_none()
        if anchor is not None:
            stmt = stmt.where(ChatMessage.created_at < anchor)
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()
    return rows
