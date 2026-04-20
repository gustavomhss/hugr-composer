from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_payment_failed(session: AsyncSession, *, stripe_session_id: str, reason: str) -> Payment | None:
    """Transition a payment to ``failed`` (idempotent)."""
    payment = await get_payment_by_session_id(session, stripe_session_id)
    if payment is None or payment.status == 'failed':
        return payment
    payment.status = 'failed'
    md = dict(payment.metadata_json or {})
    md['failure_reason'] = reason[:500]
    payment.metadata_json = md
    await session.flush()
    return payment
