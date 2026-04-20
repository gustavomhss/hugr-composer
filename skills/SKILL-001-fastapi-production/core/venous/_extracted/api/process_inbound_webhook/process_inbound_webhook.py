from __future__ import annotations
from datetime import datetime
from datetime import timezone


async def process_inbound_webhook(ctx: dict, inbound_id: str) -> None:
    """ARQ task: invoke handlers for an inbound webhook event.

    Args:
        ctx: ARQ context dict.
        inbound_id: UUID string of the ``InboundWebhook`` row to process.
    """
    async with async_session_maker() as session:
        inbound = await crud_iwh.get(session, id=inbound_id)
        if not inbound or inbound.status not in ('received',):
            return
        inbound.status = 'processing'
        await session.commit()
        event = VerifiedEvent(provider=inbound.provider, event_id=inbound.provider_event_id, event_type=inbound.event_type, payload=inbound.payload)
        handlers = get_handlers(inbound.provider, inbound.event_type)
        try:
            for handler in handlers:
                await handler(event)
            inbound.status = 'succeeded'
            inbound.processed_at = datetime.now(timezone.utc)
            logger.info('Processed inbound webhook provider=%s type=%s id=%s', inbound.provider, inbound.event_type, inbound_id)
        except Exception as exc:
            inbound.status = 'failed'
            inbound.error = repr(exc)[:500]
            inbound.processed_at = datetime.now(timezone.utc)
            logger.error('Handler failed for inbound webhook id=%s: %s', inbound_id, exc)
            raise
        finally:
            await session.commit()
