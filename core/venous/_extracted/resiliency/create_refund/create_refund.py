from __future__ import annotations
from typing import Any
import uuid


def create_refund(*, charge_id: str, amount_cents: int, payment_id: uuid.UUID, reason: str | None) -> dict[str, Any]:
    """Issue a Stripe refund with an idempotency key.

    Imports the ``stripe`` SDK lazily so the app boots without it.
    The idempotency key prevents double-refunds on retry.

    Args:
        charge_id: Stripe Charge id to refund.
        amount_cents: Amount to refund in the smallest currency unit.
        payment_id: Internal Payment UUID (used to build idempotency key).
        reason: Optional Stripe-accepted reason string.

    Returns:
        The Stripe Refund object as a plain dict.

    Raises:
        ModuleNotFoundError: If ``stripe`` is not installed.
        stripe.StripeError: If the API call fails.
    """
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = settings.STRIPE_API_VERSION
    idempotency_key = f'refund-{payment_id}-{amount_cents}'
    kwargs: dict[str, Any] = {'charge': charge_id, 'amount': amount_cents}
    if reason:
        kwargs['reason'] = reason
    result = stripe.Refund.create(**kwargs, idempotency_key=idempotency_key)
    return dict(result)
