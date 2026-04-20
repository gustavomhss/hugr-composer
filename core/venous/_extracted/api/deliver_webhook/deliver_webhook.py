from __future__ import annotations


async def deliver_webhook(ctx: dict, delivery_id: str) -> None:
    """ARQ task: attempt delivery, persist outcome, retry if needed.

    Args:
        ctx: ARQ context dict (contains ``redis`` key for enqueuing retries).
        delivery_id: UUID string of the ``WebhookDelivery`` row to process.
    """
    async with async_session_maker() as session:
        delivery = await crud_wh.get_delivery(session, id=delivery_id)
        if not delivery or delivery.status not in ('pending',):
            return
        endpoint = await crud_wh.get_endpoint(session, id=delivery.endpoint_id)
        if not endpoint or endpoint.status != 'active':
            delivery.status = 'dead'
            await session.commit()
            return
        await _attempt_delivery(delivery, endpoint)
        await session.commit()
    if delivery.status == 'pending':
        next_delay = delay_for_attempt(delivery.attempt_number + 1)
        if next_delay >= 0:
            await ctx['redis'].enqueue_job('deliver_webhook', str(delivery.id), _defer_by=next_delay)
