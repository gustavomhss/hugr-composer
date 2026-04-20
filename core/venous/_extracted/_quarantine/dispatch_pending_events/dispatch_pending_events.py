from __future__ import annotations
from datetime import datetime
from datetime import timezone
from sqlalchemy import select


async def dispatch_pending_events(ctx: dict) -> dict:
    """ARQ task: poll and dispatch a batch of pending outbox events.

    Args:
        ctx: ARQ context dict (injected by worker framework).

    Returns:
        Dict with ``dispatched`` and ``failed`` counts.
    """
    factory = await _get_session_factory()
    dispatched = failed = 0
    async with factory() as session:
        async with session.begin():
            stmt = select(OutboxEvent).where(OutboxEvent.status == 'pending', OutboxEvent.dispatched_at.is_(None)).order_by(OutboxEvent.created_at).limit(_DEFAULT_BATCH_SIZE).with_for_update(skip_locked=True)
            rows = (await session.execute(stmt)).scalars().all()
            for event in rows:
                ok = await _dispatch_event(event)
                if ok:
                    event.status = 'delivered'
                    event.dispatched_at = datetime.now(timezone.utc)
                    dispatched += 1
                else:
                    event.attempts += 1
                    if event.attempts >= _DEFAULT_MAX_RETRIES:
                        await _move_to_dlq(session, event)
                        event.status = 'dead'
                    else:
                        delay = _RETRY_DELAYS[min(event.attempts, len(_RETRY_DELAYS) - 1)]
                        logger.warning('Event %s attempt %d failed; retry in %ds', event.id, event.attempts, delay)
                    failed += 1
    logger.info('Outbox dispatch: %d dispatched, %d failed', dispatched, failed)
    return {'dispatched': dispatched, 'failed': failed}
