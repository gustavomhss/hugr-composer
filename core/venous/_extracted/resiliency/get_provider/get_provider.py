from __future__ import annotations


def get_provider() -> EmailProvider:
    """Return the provider adapter matching ``settings.EMAIL_PROVIDER``.

    Returns:
        A provider instance implementing the ``EmailProvider`` protocol.

    Raises:
        ValueError: If ``settings.EMAIL_PROVIDER`` is unknown.
    """
    name = (settings.EMAIL_PROVIDER or 'resend').lower()
    if name == 'resend':
        return ResendProvider()
    if name == 'postmark':
        return PostmarkProvider()
    if name == 'smtp':
        return SMTPProvider()
    raise ValueError(f'unknown EMAIL_PROVIDER {name!r}; expected resend|postmark|smtp')
