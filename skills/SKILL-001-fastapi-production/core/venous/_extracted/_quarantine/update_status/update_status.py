from __future__ import annotations
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession


async def update_status(session: AsyncSession, *, stripe_subscription_id: str, status: str, current_period_start: datetime | None=None, current_period_end: datetime | None=None, cancel_at_period_end: bool | None=None) -> Subscription | None:
    """Update status and billing period fields (idempotent)."""
    sub = await get_by_stripe_id(session, stripe_subscription_id)
    if sub is None:
        return None
    sub.status = status
    if current_period_start is not None:
        sub.current_period_start = current_period_start
    if current_period_end is not None:
        sub.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        sub.cancel_at_period_end = cancel_at_period_end
    await session.flush()
    return sub
