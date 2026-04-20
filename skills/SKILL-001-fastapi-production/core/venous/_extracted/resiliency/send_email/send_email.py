from __future__ import annotations
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any


async def send_email(session: AsyncSession, *, to: str, template: TemplateName, context: dict[str, Any], locale: str | None=None, user_id: Any | None=None) -> Any:
    """Render + send an email synchronously, persisting an audit row.

    Args:
        session: Async SQLAlchemy session.
        to: Recipient email address (redacted in the audit row).
        template: Template identifier.
        context: Template render context.
        locale: Preferred locale; defaults to ``settings.EMAIL_DEFAULT_LOCALE``.
        user_id: Optional user UUID for the audit FK.

    Returns:
        The persisted ``EmailDelivery`` row.

    Raises:
        Exception: Whatever the provider raises — after the audit row
            is marked failed.
    """
    effective_locale = locale or settings.EMAIL_DEFAULT_LOCALE
    rendered = render_email(template, context, effective_locale)
    redacted = _redact_email(to)
    delivery = await record_delivery(session, to_email_redacted=redacted, template_name=template.value, locale=effective_locale, provider=settings.EMAIL_PROVIDER, user_id=user_id)
    message = _build_message(rendered, to)
    try:
        result = await get_provider().send(message)
    except Exception as exc:
        logger.warning('email send failed for %s', redacted)
        await mark_delivery_failed(session, delivery.id, str(exc)[:500])
        raise
    await mark_delivery_sent(session, delivery.id, result.id)
    return delivery
