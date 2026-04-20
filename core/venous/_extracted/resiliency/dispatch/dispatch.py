from __future__ import annotations


async def dispatch(notification: object, *, channel: str='in_app') -> None:
    """Route *notification* to the handler registered for *channel*.

    The ``in_app`` channel is a no-op here because the row is already
    persisted by the CRUD layer before ``dispatch`` is called.  External
    channels (push, email) are where real side-effects happen.

    Args:
        notification: The persisted ``Notification`` ORM instance.
        channel: Delivery channel — one of ``"in_app"``, ``"push"``,
            ``"email"``.  Unknown channels are logged and ignored.
    """
    if channel == 'in_app':
        return
    if channel == 'push':
        await _send_push(notification)
    elif channel == 'email':
        logger.warning('email channel requested but add_email_templates is not installed; notification stored in-app only.')
    else:
        logger.warning('Unknown notification channel %r — ignored.', channel)
