from __future__ import annotations
import asyncio


class SMTPProvider:
    """Pure-stdlib SMTP adapter — no third-party dependency."""

    async def send(self, message: EmailMessage) -> EmailResult:
        """Send *message* via SMTP in a worker thread."""
        mime = _build_mime(message)
        msg_id = await asyncio.to_thread(_send_sync, mime)
        return EmailResult(id=str(msg_id), provider='smtp')
