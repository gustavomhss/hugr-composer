from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


async def enqueue_email(session: AsyncSession, *, to: str, template: TemplateName, context: dict[str, Any], locale: str | None=None, user_id: Any | None=None) -> Any:
    """Fire-and-forget email send, off the caller's critical path.

    When the arq worker is available (``app.worker.arq_worker`` with
    an ``ArqRedis`` pool) the send is enqueued there.  Otherwise the
    helper awaits ``send_email`` directly — in that case the caller
    is encouraged to wrap the call in ``BackgroundTasks`` at the
    route layer.

    Args:
        session: Async SQLAlchemy session.
        to: Recipient email address.
        template: Template identifier.
        context: Template render context.
        locale: Preferred locale.
        user_id: Optional user UUID.

    Returns:
        The persisted ``EmailDelivery`` row (pending or sent).
    """
    try:
        from app.worker.arq_worker import get_arq_pool
    except ImportError:
        return await send_email(session, to=to, template=template, context=context, locale=locale, user_id=user_id)
    pool = await get_arq_pool()
    await pool.enqueue_job('send_email_job', to=to, template=template.value, context=context, locale=locale, user_id=str(user_id) if user_id else None)
    return None
