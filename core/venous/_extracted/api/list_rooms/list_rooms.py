from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def list_rooms(session: AsyncSession, *, user_id: uuid.UUID, limit: int=50) -> list[ChatRoom]:
    """Return rooms the user can see (public rooms + own private).

    Args:
        session: Async database session.
        user_id: UUID of the requesting user.
        limit: Maximum number of rooms to return.

    Returns:
        List of ``ChatRoom`` instances, newest first.
    """
    stmt = select(ChatRoom).where((ChatRoom.is_private == False) | (ChatRoom.created_by == user_id)).order_by(ChatRoom.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())
