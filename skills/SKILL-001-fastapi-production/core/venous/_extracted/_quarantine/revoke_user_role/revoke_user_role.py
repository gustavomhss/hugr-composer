from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID


async def revoke_user_role(session: AsyncSession, *, user_id: UUID | str, role_id: UUID | str) -> bool:
    """Delete all UserRole bindings matching (user_id, role_id).

    Args:
        session: Async SQLAlchemy session.
        user_id: UUID of the user.
        role_id: UUID of the role to revoke.

    Returns:
        ``True`` if at least one binding was deleted, ``False`` otherwise.
    """
    uid = UUID(str(user_id))
    rid = UUID(str(role_id))
    rows = (await session.execute(select(UserRole).where(UserRole.user_id == uid, UserRole.role_id == rid))).scalars().all()
    for row in rows:
        await session.delete(row)
    await session.flush()
    return bool(rows)
