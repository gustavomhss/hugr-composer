from __future__ import annotations
import os


async def send_sms(phone: str, message: str) -> None:
    """Send an SMS message via the configured provider.

    Provider is selected via SMS_PROVIDER env var ('twilio' or 'vonage').
    Both SDKs are imported lazily inside this function.

    Args:
        phone: Recipient phone number in E.164 format.
        message: SMS message body.

    Raises:
        RuntimeError: If the provider is unknown or sending fails.
    """
    provider = os.environ.get('SMS_PROVIDER', 'twilio').lower()
    if provider == 'twilio':
        await _send_via_twilio(phone, message)
    elif provider == 'vonage':
        await _send_via_vonage(phone, message)
    else:
        raise RuntimeError(f'Unknown SMS_PROVIDER: {provider!r}')
