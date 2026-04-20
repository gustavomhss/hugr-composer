from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def list_user_payments(session: AsyncSession, user_id: uuid.UUID, limit: int=50, offset: int=0) -> tuple[list[Payment], int]:
    """Return (rows, total_count) for a user's payments."""
    total_stmt = select(func.count()).select_from(Payment).where(Payment.user_id == user_id)
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    page_stmt = select(Payment).where(Payment.user_id == user_id).order_by(Payment.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(page_stmt)).scalars().all())
    return (rows, total)
