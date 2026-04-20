from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import uuid


async def list_refunds_for_payment(session: AsyncSession, payment_id: uuid.UUID, limit: int=50, offset: int=0) -> tuple[list[Refund], int]:
    """Return (rows, total_count) for a payment's refunds."""
    total_stmt = select(func.count()).select_from(Refund).where(Refund.payment_id == payment_id)
    total = int((await session.execute(total_stmt)).scalar_one() or 0)
    page_stmt = select(Refund).where(Refund.payment_id == payment_id).order_by(Refund.created_at.desc()).limit(limit).offset(offset)
    rows = list((await session.execute(page_stmt)).scalars().all())
    return (rows, total)
