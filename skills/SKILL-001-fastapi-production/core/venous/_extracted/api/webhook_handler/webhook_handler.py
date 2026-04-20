from __future__ import annotations


def webhook_handler(provider: str, event_type: str):
    """Decorator that registers an async function as a webhook handler.

    Args:
        provider: Provider name the handler listens for.
        event_type: Event type string the handler processes.

    Returns:
        A decorator that registers and returns the wrapped function unchanged.

    Example::

        @webhook_handler("stripe", "payment_intent.succeeded")
        async def on_payment(event: VerifiedEvent) -> None:
            ...
    """

    def deco(fn):
        _HANDLERS.setdefault((provider, event_type), []).append(fn)
        return fn
    return deco
