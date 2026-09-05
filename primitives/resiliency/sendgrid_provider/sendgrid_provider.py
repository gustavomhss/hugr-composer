"""Pure Python primitive: SendgridProvider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import uuid
from datetime import datetime

class SendgridProvider:
    """Send transactional emails via SendGrid."""

    def send(self, *, to: str, subject: str, html: str, from_address: str='noreply@example.com', text: str='') -> str:
        """Send a single email via the SendGrid API.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            html: HTML body.
            from_address: Sender address (``From:`` header).
            text: Optional plaintext fallback body.

        Returns:
            The SendGrid message ID string (x-message-id header).

        Raises:
            ImportError: When the ``sendgrid`` package is not installed.
        """
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail
        except ImportError as exc:
            raise ImportError('sendgrid package is required: pip install sendgrid') from exc
        from app.core.config import settings
        message = Mail(from_email=from_address, to_emails=to, subject=subject, html_content=html)
        if text:
            from sendgrid.helpers.mail import Content
            message.add_content(Content('text/plain', text))
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        return response.headers.get('x-message-id', '')
