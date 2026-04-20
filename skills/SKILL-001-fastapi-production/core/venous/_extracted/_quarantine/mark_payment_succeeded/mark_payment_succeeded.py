from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_payment_succeeded(session: AsyncSession, *, stripe_session_id: str, payment_intent_id: str | None, stripe_customer_id: str | None) -> Payment | None:
    """Transition a payment to ``succeeded`` (idempotent)."""
    payment = await get_payment_by_session_id(session, stripe_session_id)
    if payment is None or payment.status == 'succeeded':
        return payment
    payment.status = 'succeeded'
    payment.stripe_payment_intent_id = payment_intent_id
    payment.stripe_customer_id = stripe_customer_id
    payment.succeeded_at = datetime.now(timezone.utc)
    await session.flush()
    return payment
