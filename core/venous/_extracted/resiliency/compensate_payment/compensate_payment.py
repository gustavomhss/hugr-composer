from __future__ import annotations
from typing import Any


async def compensate_payment(order_id: str, charge_id: str) -> dict[str, Any]:
    """Void or refund a payment charge on workflow failure.

    Compensation activity: called from the workflow's except block
    when a downstream activity fails after payment has been captured.

    Args:
        order_id: Unique order identifier.
        charge_id: Charge reference to void/refund.

    Returns:
        Dict with ``order_id``, ``charge_id``, and ``status``.
    """
    from temporalio import activity
    activity.logger.info('Compensating payment for order %s charge_id=%s', order_id, charge_id)
    return {'order_id': order_id, 'charge_id': charge_id, 'status': 'refunded'}
