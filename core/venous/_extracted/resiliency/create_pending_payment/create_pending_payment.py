from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any
import uuid


async def create_pending_payment(session: AsyncSession, *, user_id: uuid.UUID | None, amount_cents: int, currency: str, stripe_session_id: str, product_name: str | None, customer_email: str | None, metadata_json: dict[str, Any] | None) -> Payment:
    """Insert a ``pending`` Payment row for a new Checkout Session."""
    payment = Payment(user_id=user_id, amount_cents=amount_cents, currency=currency.upper(), stripe_session_id=stripe_session_id, product_name=product_name, customer_email=customer_email, metadata_json=metadata_json, status='pending')
    session.add(payment)
    await session.flush()
    return payment
