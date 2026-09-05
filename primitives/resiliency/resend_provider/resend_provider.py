"""Pure Python primitive: ResendProvider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class ResendProvider:
    """Resend HTTP API adapter.

    Imports the ``resend`` package lazily so the app boots without
    it.  Uses ``resend.Emails.send`` which wraps the POST /emails
    endpoint.  The API key is read on every call from settings and
    NEVER logged.
    """

    async def send(self, message: EmailMessage) -> EmailResult:
        """Send *message* via Resend."""
        import resend
        resend.api_key = settings.RESEND_API_KEY
        payload = {'from': f'{message.from_name} <{message.from_}>' if message.from_name else message.from_, 'to': [message.to], 'subject': message.subject, 'html': message.html, 'text': message.text}
        if message.reply_to:
            payload['reply_to'] = message.reply_to
        response = resend.Emails.send(payload)
        msg_id = (response.get('id') if isinstance(response, dict) else getattr(response, 'id', '')) or ''
        return EmailResult(id=str(msg_id), provider='resend')
