from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def get_by_user(session: AsyncSession, user_id: uuid.UUID, limit: int=20, offset: int=0) -> tuple[list[Subscription], int]:
    """Return (rows, total_count) for a user's subscriptions."""
    total_stmt = select(func.count()).select_from(Subscription).where(Subscription.user_id == user_id)
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    page_stmt = select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(page_stmt)).scalars().all())
    return (rows, total)
