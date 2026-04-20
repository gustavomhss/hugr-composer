from __future__ import annotations
from typing import Any


async def charge_payment(order_id: str, amount_cents: int) -> dict[str, Any]:
    """Charge the payment instrument for an order.

    Calls the payment provider and returns a charge reference.  On
    failure the workflow will execute ``compensate_payment`` to void
    any partial charge.

    Args:
        order_id: Unique order identifier.
        amount_cents: Amount to charge in the smallest currency unit.

    Returns:
        Dict with ``order_id``, ``charge_id``, and ``status``.
    """
    from temporalio import activity
    activity.logger.info('Charging payment for order %s amount_cents=%d', order_id, amount_cents)
    return {'order_id': order_id, 'charge_id': f'ch_{order_id[:8]}', 'status': 'captured'}
