from __future__ import annotations
from typing import Any


async def fulfil_order(order_id: str, charge_id: str) -> dict[str, Any]:
    """Fulfil an order after successful payment.

    Triggers inventory deduction, dispatch, and notification.

    Args:
        order_id: Unique order identifier.
        charge_id: Charge reference returned by ``charge_payment``.

    Returns:
        Dict with ``order_id``, ``fulfillment_id``, and ``status``.
    """
    from temporalio import activity
    activity.logger.info('Fulfilling order %s charge_id=%s', order_id, charge_id)
    return {'order_id': order_id, 'fulfillment_id': f'ff_{order_id[:8]}', 'status': 'dispatched'}
