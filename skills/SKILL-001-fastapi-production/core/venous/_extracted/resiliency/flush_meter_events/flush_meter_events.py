from __future__ import annotations


def flush_meter_events(batch_size: int=100) -> int:
    """Flush pending meter events to Stripe in one batch.

    Args:
        batch_size: Maximum number of events to flush per call.

    Returns:
        Number of events successfully submitted.
    """
    from app.billing.metering import get_event_buffer
    from app.core.config import settings
    buffer = get_event_buffer()
    if buffer.size == 0:
        return 0
    batch = buffer.drain(batch_size)
    if not batch:
        return 0
    submitted = 0
    for event in batch:
        success = _submit_with_retry(event, settings.STRIPE_METER_API_KEY)
        if success:
            submitted += 1
        else:
            _DEAD_LETTER.append({'tenant_id': event.tenant_id, 'endpoint': event.endpoint, 'timestamp': event.timestamp})
            logger.error('Dead-lettered meter event for tenant=%s', event.tenant_id)
    return submitted
