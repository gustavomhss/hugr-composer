from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def check_user_can_join(session: AsyncSession, *, room_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Return whether *user_id* is allowed to join *room_id*.

    Public rooms allow any authenticated user.  Private rooms are
    restricted to their creator in this minimal model — richer
    access-control lives in a future ACL table.

    Args:
        session: Async database session.
        room_id: UUID of the target room.
        user_id: UUID of the requesting user.

    Returns:
        ``True`` if the user may join.
    """
    room = await get_room(session, room_id=room_id)
    if room is None:
        return False
    if not room.is_private:
        return True
    return room.created_by == user_id
